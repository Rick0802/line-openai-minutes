from sqlalchemy import Column, String, Boolean, DateTime, Text, Date, ForeignKey, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import os

Base = declarative_base()

class Group(Base):
    __tablename__ = 'groups'
    
    group_id = Column(String, primary_key=True)
    group_name = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship("Message", back_populates="group")
    topics = relationship("Topic", back_populates="group")

class Message(Base):
    __tablename__ = 'messages'
    
    message_id = Column(String, primary_key=True)
    group_id = Column(String, ForeignKey('groups.group_id'))
    topic_id = Column(String, ForeignKey('topics.topic_id'), nullable=True)
    user_id = Column(String)
    message_text = Column(Text)
    reply_to_id = Column(String, nullable=True)
    is_analyzed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    group = relationship("Group", back_populates="messages")
    topic = relationship("Topic", back_populates="messages")

class Topic(Base):
    __tablename__ = 'topics'
    
    topic_id = Column(String, primary_key=True)
    group_id = Column(String, ForeignKey('groups.group_id'))
    title = Column(String)
    status = Column(String, default='open')
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    group = relationship("Group", back_populates="topics")
    messages = relationship("Message", back_populates="topic")
    todos = relationship("Todo", back_populates="topic")

class Todo(Base):
    __tablename__ = 'todos'
    
    todo_id = Column(String, primary_key=True)
    topic_id = Column(String, ForeignKey('topics.topic_id'))
    detail = Column(Text)
    assignee = Column(String)
    due_date = Column(Date, nullable=True)
    status = Column(String, default='pending')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    topic = relationship("Topic", back_populates="todos")

def init_db():
    engine = create_engine(os.getenv('DATABASE_URL'))
    Base.metadata.create_all(engine)