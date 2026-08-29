from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort
from models import db, Activity, Registration, Prize, GrabRecord
from datetime import datetime
import re
from db_checker import check_phone_registered
import random
from config import DB_CONFIG
import pymysql
from coupon_service import issue_coupon_to_shop
import threading
import uuid
import os
import json
from waitress import serve

# 进程锁，防止多人同时抢碰撞
grab_lock = threading.Lock()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'hcjtyyglzxwangyuwenkaifa'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///coupon.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

db.init_app(app)

def get_remote_connection():
    """连接远商城数据库（配置取自 config.py 的 DB_CONFIG）"""
    return pymysql.connect(
        host=DB_CONFIG['host'],
        port=DB_CONFIG['port'],
        user=DB_CONFIG['user'],
        password=DB_CONFIG['password'],
        database=DB_CONFIG['database'],
        charset='utf8mb4',
        connect_timeout=10
    )

# 判断是否在活动时间内
def is_within_activity_time(times_str):
    if not times_str:
        return False
    now = datetime.now()
    safe_times = times_str.replace('，', ',')
    time_slots = [t.strip() for t in safe_times.split(',')]

    for slot in time_slots:
        try:
            date_part, time_range = slot.split(' ')
            start_time_str, end_time_str = time_range.split('-')
            start_dt = datetime.strptime(f"{date_part} {start_time_str}", "%Y-%m-%d %H:%M")
            end_dt = datetime.strptime(f"{date_part} {end_time_str}", "%Y-%m-%d %H:%M")
            if start_dt <= now <= end_dt:
                return True
        except Exception:
            continue

    return False

# 抽奖核心概率代码
def draw_prize(activity_code):
    """根据概率抽取奖品，返回 Prize 对象或 None"""
    prizes = Prize.query.filter_by(activity_code=activity_code)\
                        .order_by(Prize.rank_no).all()

    # 只从还有库存的奖品里抽
    prizes = [p for p in prizes if p.granted < p.stock]
    if not prizes:
        return None

    # 校验概率合计是否为1（允许微小误差）
    total_p = sum(p.probability for p in prizes)
    if total_p > 1.0 + 0.001:
        print(f"错误：活动{activity_code}概率合计={total_p}，超过1！"
              f"超出部分会被截断，请到后台修正奖品概率")

    r = random.random()
    cumulative = 0.0
    for p in prizes:
        cumulative += p.probability
        if r < cumulative:
            return p
    return None   # 未命中任何区间 → 谢谢参与

# 前台路由
@app.route('/activity/<code>')
def view_activity(code):
    activity = Activity.query.filter_by(code=code).first_or_404()
    is_active_time = is_within_activity_time(activity.times)

    # 剩余名额 = 所有奖品(总数-已发出)之和
    prizes = Prize.query.filter_by(activity_code=activity.code).all()
    prize_total_stock = sum(p.stock for p in prizes)
    prize_granted = sum(p.granted for p in prizes)
    remain_prizes = max(0, prize_total_stock - prize_granted)
    is_full = remain_prizes <= 0

    return render_template('activity.html', activity=activity,
                           is_active_time=is_active_time, is_full=is_full,
                           remain_prizes=remain_prizes,
                           prize_total_stock=prize_total_stock)

# 根据数据库已有优惠券名称拉取优惠券
@app.route('/admin/coupon_names', methods=['GET'])
def admin_coupon_names():
    """从数据库券表拉取可配置为奖品的券名列表"""
    conn = get_remote_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT template_name 
            FROM vehicle_erp.coupon_template 
            WHERE coupon_type = 4 
              AND goods_type = 3 
              AND validity_type = 2 
              AND status = 1 
              AND coupon_source = 4
            ORDER BY template_name
        """)
        names = [row[0] for row in cursor.fetchall()]
        return jsonify({'success': True, 'names': names})
    except Exception as e:
        print(f"[券名查询失败] {e}")
        return jsonify({'success': False, 'names': [], 'msg': str(e)})
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass

# 上传活动设置中图文信息图片专用
@app.route('/admin/upload_image', methods=['POST'])
def upload_image():
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'msg': '未登录'}), 401

    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'success': False, 'msg': '未收到文件'})

    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
    if ext not in ALLOWED_EXT:
        return jsonify({'success': False, 'msg': f'不支持的格式 .{ext}'})

    # 用随机文件名，防止重名覆盖和路径注入
    filename = f"{uuid.uuid4().hex}.{ext}"
    f.save(os.path.join(UPLOAD_DIR, filename))

    return jsonify({'success': True, 'url': f'/static/uploads/{filename}'})

# 抢券核心代码
@app.route('/api/grab_coupon', methods=['POST'])
def grab_coupon():
    data = request.get_json()
    phone = data.get('phone', '').strip()
    activity_code = data.get('activity_code')

    # 手机号格式校验（前端已经查了一遍，但这里还是加，作为双保险）
    if not re.match(r'^1[3-9]\d{9}$', phone):
        return jsonify({'success': False, 'msg': '请输入正确的11位手机号'}), 400

    activity = Activity.query.filter_by(code=activity_code).first()
    if not activity:
        return jsonify({'success': False, 'msg': '活动不存在'}), 404

    # 后台强校验活动时间
    if not is_within_activity_time(activity.times):
        return jsonify({'success': False, 'msg': '此活动当前不可用，不在活动时间内'}), 403

    with grab_lock:
        # ===== 用户资格校验 =====

        # 抢券次数上限
        used_count = Registration.query.filter_by(
            activity_id=activity.id, phone=phone).count()
        max_grab_count = activity.max_grab_count if activity.max_grab_count else 1
        if used_count >= max_grab_count:
            return jsonify({
                'success': False,
                'msg': f'您的抢券次数已用完（{max_grab_count}次上限）',
                'remaining': 0,
                'no_chance': True
            }), 400

        # 同一手机号本活动限中奖1次，中奖后剩余次数只能陪跑
        if Registration.query.filter_by(
                activity_id=activity.id, phone=phone,
                is_win=True).count() > 0:
            return jsonify({
                'success': False,
                'msg': '您已中奖过啦，把机会留给其他小伙伴吧~',
                'remaining': 0,
                'no_chance': True
            }), 400

        # 远程校验是否已注册商城
        if not check_phone_registered(phone):
            return jsonify({'success': False, 'need_redirect': True,
                            'msg': '您尚未在小程序注册，请先去小程序注册'}), 403

        # ===== 活动库存校验 =====

        prizes = Prize.query.filter_by(activity_code=activity.code).all()
        prize_remaining = sum(max(0, p.stock - p.granted) for p in prizes)
        if prize_remaining <= 0:
            return jsonify({'success': False, 'msg': '抱歉，名额已满！'}), 400

        # ===== 抽奖 + 扣库存 + 落库 =====

        won_prize = draw_prize(activity_code)

        coupon_issued = False
        if won_prize:
            won_prize.granted += 1     # 扣减奖品库存
            coupon_issued = issue_coupon_to_shop(phone, won_prize.coupon_name)
            if not coupon_issued:
                db.session.rollback()   # granted 自增一并回滚，如果券未能成功发放，之前记录回滚
                return jsonify({
                    'success': False,
                    'msg': '系统繁忙，发券服务异常，请稍后再试'
                }), 500

        # 无论是否中奖都记录一次抢券
        new_reg = Registration(
            activity_id=activity.id,
            phone=phone,
            is_registered_mall=True,
            is_win=bool(won_prize),
            prize_name=(f'{won_prize.rank_no}等奖-{won_prize.coupon_name}' if won_prize else None)
        )
        db.session.add(new_reg)
        db.session.commit()

        remaining_times = max(0, max_grab_count - used_count - 1)

        if won_prize:
            msg = (f'🎉 恭喜获得{won_prize.rank_no}等奖奖品：'
                   f'{won_prize.coupon_name}，券已自动发放到您的账户！')
        else:
            msg = f'很遗憾，本轮未中奖~ 您还有 {remaining_times} 次机会'

        return jsonify({
            'success': True,
            'is_win': bool(won_prize),
            'prize_rank': won_prize.rank_no if won_prize else None,
            'prize_name': won_prize.coupon_name if won_prize else None,
            'coupon_issued': coupon_issued,
            'remaining': remaining_times,
            'prize_remaining': prize_remaining - (1 if won_prize else 0),
            'msg': msg
        }), 200


# 查询剩余次数的接口（用户进入页面时显示）
@app.route('/api/grab_info', methods=['GET'])
def grab_info():
    activity_code = request.args.get('activity_code')
    phone = request.args.get('phone')
    activity = Activity.query.filter_by(code=activity_code).first()
    if not activity:
        return jsonify({'max_count': 0, 'used': 0, 'remaining': 0})
    used = Registration.query.filter_by(
        activity_id=activity.id, phone=phone).count()
    max_count = activity.max_grab_count if activity.max_grab_count else 1
    remaining = max(0, max_count - used)
    return jsonify({
        'max_count': max_count,
        'used': used,
        'remaining': remaining
    })

# 保存活动设置（图文 + 最大次数 + 奖品列表一起提交）
@app.route('/admin/save_activity_setting', methods=['POST'])
def save_activity_setting():
    data = request.get_json()
    code = data['activity_code']
    activity = Activity.query.filter_by(code=code).first()

    activity.rich_text = data.get('rich_text', '')
    activity.max_grab_count = int(data.get('max_grab_count', 3))

    total = sum(float(i['probability']) for i in data.get('prizes', []))
    if total > 1.0001:
        return jsonify({'success': False,
                        'msg': f'概率合计为{total}，不能超过1，请修正后再保存'}), 400

    Prize.query.filter_by(activity_code=code).delete()
    for item in data.get('prizes', []):
        p = Prize(
            activity_code=code,
            rank_no=item['rank_no'],
            coupon_name=item['coupon_name'],
            probability=float(item['probability']),
            stock=int(item.get('stock', 0)),
            granted=0      # 重设奖品时已发出清零
        )
        db.session.add(p)

    db.session.commit()
    return jsonify({'success': True, 'total_probability': total})

# 虚拟登录，写死登录名和密码，管理员使用，所以没有做复杂登录设置
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == 'admin' and password == 'admin':
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        return render_template('admin_login.html', error='账号或密码错误')
    return render_template('admin_login.html')

# 登出
@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

# 管理面板
@app.route('/admin')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    activities = Activity.query.all()
    # 每个活动的奖品库存统计（剩余/总数/奖品个数）
    stats = {}
    for act in activities:
        prizes = Prize.query.filter_by(activity_code=act.code).all()
        total = sum(p.stock for p in prizes)
        granted = sum(p.granted for p in prizes)
        stats[act.id] = {'total': total, 'remain': max(0, total - granted),
                         'prize_count': len(prizes)}
    return render_template('admin_dashboard.html', activities=activities, stats=stats)

# 创建活动
@app.route('/admin/activity/create', methods=['POST'])
def create_activity():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    code = request.form.get('code', '').strip()
    name = request.form.get('name', '').strip()
    times = request.form.get('times', '').strip()

    if not code or not name:
        return '活动代码和名称不能为空', 400
    if Activity.query.filter_by(code=code).first():
        return '活动代码已存在，请更换！', 400

    # 解析奖品配置（前端提交的 prizes_json）
    try:
        prizes_data = json.loads(request.form.get('prizes_json', '[]'))
    except (ValueError, TypeError):
        return '奖品数据格式错误', 400

    if not prizes_data:
        return '至少要设置一个奖品', 400

    total_prob = sum(float(p.get('probability', 0)) for p in prizes_data)
    if total_prob > 1.0001:
        return f'概率合计为 {total_prob:.2f}，不能超过 1', 400
    if any(int(p.get('stock', 0)) <= 0 for p in prizes_data):
        return '每个奖品的发放数量必须大于 0', 400

    activity = Activity(
        code=code, name=name, times=times,
        quota=0,# 名额已由奖品库存决定，此字段仅保留兼容
        max_grab_count=int(request.form.get('max_grab_count', 1)),
        rich_text=request.form.get('rich_text', '')
    )
    db.session.add(activity)
    db.session.flush()   # commit 前先拿到 activity.id

    for item in prizes_data:
        db.session.add(Prize(
            activity_code=code,
            rank_no=int(item['rank_no']),
            coupon_name=item['coupon_name'],
            probability=float(item['probability']),
            stock=int(item.get('stock', 0)),
            granted=0
        ))

    db.session.commit()
    return redirect(url_for('admin_dashboard'))

# 删除活动
@app.route('/admin/activity/delete/<int:act_id>', methods=['POST'])
def delete_activity(act_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    activity = Activity.query.get(act_id)
    if activity:
        Registration.query.filter_by(activity_id=act_id).delete()
        Prize.query.filter_by(activity_code=activity.code).delete()
        db.session.delete(activity)
        db.session.commit()
    return redirect(url_for('admin_dashboard'))

# 构成任意活动链接
@app.route('/admin/activity/detail/<int:act_id>')
def activity_detail(act_id):
    activity = Activity.query.get_or_404(act_id)

    regs = Registration.query.filter_by(activity_id=activity.id)\
        .order_by(Registration.register_time.desc()).all()
    prizes = Prize.query.filter_by(activity_code=activity.code)\
        .order_by(Prize.rank_no).all()

    prize_total_stock = sum(p.stock for p in prizes)
    prize_granted = sum(p.granted for p in prizes)
    registered_phones = len({r.phone for r in regs})

    return render_template('admin_detail.html',
                           activity=activity,
                           regs=regs,
                           prizes=prizes,
                           prize_total_stock=prize_total_stock,
                           prize_granted=prize_granted,
                           registered_phones=registered_phones)

# 管理面板活动详情(可查看并编辑活动以及活动当前中奖明细数据)
@app.route('/admin/update_activity_detail', methods=['POST'])
def update_activity_detail():
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'msg': '未登录'}), 401

    data = request.get_json()
    code = data.get('activity_code')
    activity = Activity.query.filter_by(code=code).first()
    if not activity:
        return jsonify({'success': False, 'msg': '活动不存在'}), 404

    # 校验奖品数据
    prizes_data = data.get('prizes', [])
    total_prob = sum(float(p.get('probability', 0)) for p in prizes_data)
    if total_prob > 1.0001:
        return jsonify({'success': False,
                        'msg': f'概率合计 {total_prob:.4f}，不能超过1'}), 400

    for p in prizes_data:
        prize = Prize.query.get(p['id'])
        if not prize or prize.activity_code != code:   # 防止越权改别家活动
            continue
        if int(p['stock']) < prize.granted:            # 后端兜底库存校验
            return jsonify({'success': False,
                            'msg': f'{prize.rank_no}等奖库存不能低于已发出的{prize.granted}'}), 400

    # 通过校验后才落库
    for p in prizes_data:
        prize = Prize.query.get(p['id'])
        prize.probability = float(p['probability'])
        prize.stock = int(p['stock'])

    activity.rich_text = data.get('rich_text', '')
    db.session.commit()
    return jsonify({'success': True})



if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)

# 正式运行使用此代码，因为我是windows服务器+nginx，所以使用waitress库，linux服务器不要用这个库
# if __name__ == '__main__':
#     with app.app_context():
          # print('创建数据文件...')
#         db.create_all()

#     # 生产环境：使用 waitress 运行（替代 Flask 自带开发服务器）
      # print('建表完成，启动waitress...')
#     serve(app, host="127.0.0.1", port=5000, threads=8)