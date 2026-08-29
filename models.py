from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Activity(db.Model):
    __tablename__ = 'activities'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)  # 活动代码，用于URL
    name = db.Column(db.String(100), nullable=False)             # 活动名称
    quota = db.Column(db.Integer, nullable=False, default=0)     # 名额
    times = db.Column(db.Text, nullable=False)                   # 活动时间，存储多个时间段，如 "2026-08-26 10:00-12:00,2026-08-27 14:00-16:00"
    rich_text = db.Column(db.Text)                # 图文说明HTML
    max_grab_count = db.Column(db.Integer, default=3)  # 最大抢券次数
    registrations = db.relationship('Registration', backref='activity', lazy=True)

class Registration(db.Model):
    __tablename__ = 'registrations'
    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey('activities.id'), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    is_registered_mall = db.Column(db.Boolean, default=False)
    register_time = db.Column(db.DateTime, default=db.func.current_timestamp())
    grab_count = db.Column(db.Integer, default=0)      # 已使用抢券次数
    is_win = db.Column(db.Boolean, default=False)      # 本次是否中奖
    prize_name = db.Column(db.String(100))             # 中到的券名
    win_time = db.Column(db.DateTime)                  # 中奖时间

# ===== 奖品表 =====
class Prize(db.Model):
    __tablename__ = 'prize'
    id = db.Column(db.Integer, primary_key=True)
    activity_code = db.Column(db.String(50), nullable=False)
    rank_no = db.Column(db.Integer, nullable=False)          # 第几名
    coupon_name = db.Column(db.String(100), nullable=False)  # 券名
    probability = db.Column(db.Float, nullable=False)        # 概率
    stock = db.Column(db.Integer, nullable=False, default=0)      # 该奖品总数
    granted = db.Column(db.Integer, nullable=False, default=0)    # 已发出数量

# ===== 抢券记录表 =====
class GrabRecord(db.Model):
    __tablename__ = 'grab_record'
    id = db.Column(db.Integer, primary_key=True)
    activity_code = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    is_win = db.Column(db.Boolean, default=False)
    prize_rank = db.Column(db.Integer, nullable=True)
    coupon_name = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

