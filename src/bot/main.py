from fastapi import FastAPI, Request, HTTPException
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    SourceGroup
)
import os
import json
import boto3
from ..lib.database import get_db
from ..lib.models import Group, Message
import uuid
from datetime import datetime

app = FastAPI()

# LINE Bot設定
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

# AWS SQS設定（オプション）
sqs = boto3.client('sqs',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_REGION')
) if os.getenv('AWS_SQS_QUEUE_URL') else None

@app.post("/webhook")
async def webhook(request: Request):
    signature = request.headers['X-Line-Signature']
    body = await request.body()
    
    try:
        handler.handle(body.decode(), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    if not isinstance(event.source, SourceGroup):
        return

    group_id = event.source.group_id
    user_id = event.source.user_id
    message_text = event.message.text
    reply_token = event.reply_token

    # データベースに保存
    with get_db() as db:
        # グループが存在しない場合は作成
        group = db.query(Group).filter(Group.group_id == group_id).first()
        if not group:
            group = Group(group_id=group_id)
            db.add(group)
            db.commit()

        # メッセージを保存
        message = Message(
            message_id=str(uuid.uuid4()),
            group_id=group_id,
            user_id=user_id,
            message_text=message_text,
            reply_to_id=event.message.quote_token if hasattr(event.message, 'quote_token') else None
        )
        db.add(message)
        db.commit()

        # 未解析メッセージのカウントをチェック
        unanalyzed_count = db.query(Message).filter(
            Message.group_id == group_id,
            Message.is_analyzed == False
        ).count()

    # コマンド処理
    if message_text.startswith('@Bot '):
        command = message_text[5:].strip()
        
        if command == 'まとめ':
            # SQSが設定されている場合はキューに投入
            if sqs:
                sqs.send_message(
                    QueueUrl=os.getenv('AWS_SQS_QUEUE_URL'),
                    MessageBody=json.dumps({
                        'type': 'summarize',
                        'group_id': group_id,
                        'reply_token': reply_token
                    })
                )
                line_bot_api.reply_message(
                    reply_token,
                    TextSendMessage(text='要約を作成中です。しばらくお待ちください。')
                )
            else:
                # 同期的に処理（本番環境では非推奨）
                line_bot_api.reply_message(
                    reply_token,
                    TextSendMessage(text='申し訳ありません。現在この機能は利用できません。')
                )
        
        elif command == 'help':
            help_text = """🤖 使い方ガイド
- @Bot まとめ : 直近の会話を要約します
- @Bot help : このヘルプを表示します"""
            line_bot_api.reply_message(
                reply_token,
                TextSendMessage(text=help_text)
            )

    # 20件たまったら解析をトリガー
    elif unanalyzed_count >= 20 and sqs:
        sqs.send_message(
            QueueUrl=os.getenv('AWS_SQS_QUEUE_URL'),
            MessageBody=json.dumps({
                'type': 'analyze',
                'group_id': group_id
            })
        )

@app.get("/health")
def health_check():
    return {"status": "healthy"}