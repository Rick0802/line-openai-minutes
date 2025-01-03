import os
import json
import time
import boto3
import openai
from linebot import LineBotApi
from linebot.models import TextSendMessage
from ..lib.database import get_db
from ..lib.models import Message, Topic, Todo
import uuid
from datetime import datetime, timedelta
import logging

# ロギング設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# LINE Bot設定
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))

# OpenAI設定
openai.api_key = os.getenv('OPENAI_API_KEY')

# AWS SQS設定
sqs = boto3.client('sqs',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_REGION')
)

def analyze_topic(messages):
    """メッセージ群からトピックを解析"""
    # 簡易的な実装: 時系列で近いメッセージをグループ化
    if not messages:
        return None
    
    messages = sorted(messages, key=lambda x: x.created_at)
    current_topic = None
    
    for msg in messages:
        if not current_topic:
            current_topic = Topic(
                topic_id=str(uuid.uuid4()),
                group_id=msg.group_id,
                title=f"Topic {msg.created_at.strftime('%Y-%m-%d %H:%M')}"
            )
        elif (msg.created_at - messages[0].created_at) > timedelta(hours=1):
            # 1時間以上経過していたら新しいトピック
            current_topic = Topic(
                topic_id=str(uuid.uuid4()),
                group_id=msg.group_id,
                title=f"Topic {msg.created_at.strftime('%Y-%m-%d %H:%M')}"
            )
        
        msg.topic_id = current_topic.topic_id
        msg.is_analyzed = True
    
    return current_topic

def summarize_messages(messages):
    """OpenAIを使用してメッセージを要約"""
    if not messages:
        return None
    
    # メッセージを整形
    conversation = "\n".join([
        f"User {msg.user_id}: {msg.message_text}"
        for msg in sorted(messages, key=lambda x: x.created_at)
    ])
    
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": """
                あなたは議事録作成AIです。以下の会話を要約し、以下のJSON形式で出力してください：
                {
                    "summary": "会話の要約",
                    "decisions": ["重要な決定事項1", "決定事項2"...],
                    "todos": [
                        {
                            "task": "タスク内容",
                            "assignee": "担当者",
                            "due_date": "期限（YYYY-MM-DD形式）"
                        }
                    ]
                }
                """},
                {"role": "user", "content": conversation}
            ],
            temperature=0.7
        )
        
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        return None

def process_message(message_body):
    """メッセージを処理"""
    data = json.loads(message_body)
    
    with get_db() as db:
        if data['type'] == 'analyze':
            # トピック解析
            messages = db.query(Message).filter(
                Message.group_id == data['group_id'],
                Message.is_analyzed == False
            ).all()
            
            if messages:
                topic = analyze_topic(messages)
                if topic:
                    db.add(topic)
                    db.commit()
        
        elif data['type'] == 'summarize':
            # 要約処理
            messages = db.query(Message).filter(
                Message.group_id == data['group_id']
            ).order_by(Message.created_at.desc()).limit(100).all()
            
            summary_data = summarize_messages(messages)
            if summary_data:
                # ToDoを保存
                topic_id = messages[0].topic_id if messages else None
                if topic_id:
                    for todo_data in summary_data.get('todos', []):
                        todo = Todo(
                            todo_id=str(uuid.uuid4()),
                            topic_id=topic_id,
                            detail=todo_data['task'],
                            assignee=todo_data['assignee'],
                            due_date=datetime.strptime(todo_data['due_date'], '%Y-%m-%d').date()
                            if todo_data.get('due_date') else None
                        )
                        db.add(todo)
                    
                    # トピックの要約を更新
                    topic = db.query(Topic).filter(Topic.topic_id == topic_id).first()
                    if topic:
                        topic.summary = summary_data['summary']
                    
                    db.commit()
                
                # LINE に要約を送信
                summary_text = f"""📝 会話の要約:
{summary_data['summary']}

🎯 重要な決定事項:
{"".join([f"・{d}\\n" for d in summary_data['decisions']])}
📋 ToDo:
{"".join([f"・{t['task']} (@{t['assignee']})\\n" for t in summary_data['todos']])}"""
                
                line_bot_api.reply_message(
                    data['reply_token'],
                    TextSendMessage(text=summary_text)
                )

def main():
    """メインのワーカーループ"""
    queue_url = os.getenv('AWS_SQS_QUEUE_URL')
    
    while True:
        try:
            # メッセージを受信
            response = sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20
            )
            
            messages = response.get('Messages', [])
            
            for message in messages:
                try:
                    process_message(message['Body'])
                    
                    # 処理済みメッセージを削除
                    sqs.delete_message(
                        QueueUrl=queue_url,
                        ReceiptHandle=message['ReceiptHandle']
                    )
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
        
        except Exception as e:
            logger.error(f"Error in worker loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()