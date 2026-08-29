# -*- coding: utf-8 -*-
"""
优惠券自动发放服务（原生编码版 + 库存扣减 + 操作日志留痕）
用法：from coupon_service import issue_coupon_to_shop
      ok = issue_coupon_to_shop('138xxxxxxxx', 'xxx优惠券')
这部分均为自有系统逻辑，外挂在原系统基础上进行数据注入以实现发券功能，而不需要变动原系统代码
代码仅供参考，如需使用，可考虑根据自己挂载系统进行重新编写，逻辑只是根据传入手机号和优惠券名称参数进行发券而已，完成后供app.py调用
"""
import os
import time
import uuid
import pymysql
import datetime as dt

from config import DB_CONFIG
from sm4_util import encrypt_phone

LOG_DIR = 'issue_logs'# 操作日志目录（含成功与失败）

def _get_log_file():
    """当前月的日志文件名，如 issue_history_202608.log；跨月自动切新文件"""
    return os.path.join(
        LOG_DIR, f"issue_history_{dt.datetime.now().strftime('%Y%m')}.log")

DEDUCT_TOTAL = False


def get_remote_connection():
    return pymysql.connect(
        host=DB_CONFIG['host'],
        port=DB_CONFIG['port'],
        user=DB_CONFIG['user'],
        password=DB_CONFIG['password'],
        database=DB_CONFIG['database'],
        charset='utf8mb4',
        connect_timeout=10
    )


# ============================================================
# 重构单据生成编码：时间戳hex(8) + 机器标识(15) + 全局自增计数器(3)
# 特性：步长恒为+2；计数器全局持久递增、跨天不重置；两表共用同一序列；同秒多条靠尾段区分
# ============================================================
NODE_ID = '2ea2e40d4de3c9'
COUNTER_MAX = 0xFFF


def _get_next_counter(cursor):
    """
    扫 order_main 与 payment_record 中全部本节点编码，
    取尾段最大值 +2（全局持久自增，不按天重置）
    """
    cursor.execute("""
        SELECT order_no FROM vehicle_erp.order_main
         WHERE order_no LIKE %s AND LENGTH(order_no) = 26
        UNION ALL
        SELECT payment_no FROM vehicle_erp.payment_record
         WHERE payment_no LIKE %s AND LENGTH(payment_no) = 26
    """, (NODE_ID + '%', NODE_ID + '%'))
    max_counter = -2
    for (no,) in cursor.fetchall():
        try:
            c = int(no[-3:], 16)
            if c > max_counter:
                max_counter = c
        except ValueError:
            continue
    return max_counter + 2, format(int(time.time()), '08x')


def make_native_code(cursor):
    """生成一条原生风格编码；序列耗尽时借下一秒并回到起始基数"""
    counter, ts_hex = _get_next_counter(cursor)
    if counter > COUNTER_MAX:
        ts_hex = format(int(time.time()) + 1, '08x')
        counter = 0x80
    return f"{ts_hex}{NODE_ID}{format(counter, '03x')}"


def make_unique_code(cursor, check_sql, generate_fn, max_retry=10):
    """查重兜底框架：候选码查库不存在才返回，重复则重新生成"""
    for _ in range(max_retry):
        code = generate_fn()
        cursor.execute(check_sql, (code,))
        if not cursor.fetchone():
            return code
    raise RuntimeError("编码重试10次仍重复")


def gen_coupon_no():
    """券码：CPN + yyyyMMddHHmmss + A009 + '-' + UUID"""
    ts = time.strftime("%Y%m%d%H%M%S")
    return f"CPN{ts}A009-{uuid.uuid4()}"


# ============================================================
# 操作日志：追加式持久留痕（成功记插入id与回滚SQL，失败记原因）
# ============================================================
def _append_log(lines):
    """lines 为字符串列表，逐行追加到当月日志文件"""
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(_get_log_file(), 'a', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def _log_success(inserted, phone, coupon_name, coupon_no,
                 payment_no, order_no, template_id):
    ts = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    lines = [
        "",
        f"[{ts}] ======== 发券成功 ========",
        f"手机号={phone} 券名={coupon_name} template_id={template_id}",
        f"coupon_issue.id={inserted['coupon_issue']} "
        f"payment_record.id={inserted['payment_record'][0]} "
        f"order_main.id={inserted['order_main']}",
        f"coupon_no={coupon_no} payment_no={payment_no} order_no={order_no}",
        "-- ↓↓↓ 回滚SQL（黏贴到MySQL执行即可撤销本次发券）↓↓↓",
        "START TRANSACTION;",
        f"DELETE FROM vehicle_erp.order_main WHERE id = {inserted['order_main']};",
        f"DELETE FROM vehicle_erp.payment_record WHERE id = {inserted['payment_record'][0]};",
        f"DELETE FROM vehicle_erp.coupon_issue WHERE id = {inserted['coupon_issue']};",
        f"UPDATE vehicle_erp.coupon_template SET issued_quantity = issued_quantity - 1"
        f"{' , total_quantity = total_quantity + 1' if DEDUCT_TOTAL else ''}"
        f" WHERE id = {template_id};",
        "COMMIT;",
        "-- ↑↑↑ 回滚SQL结束 ↑↑↑",
    ]
    _append_log(lines)


def _log_failure(phone, coupon_name, reason):
    ts = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    lines = [
        "",
        f"[{ts}] ======== 发券失败 ========",
        f"手机号={phone} 券名={coupon_name}",
        f"原因: {reason}",
    ]
    _append_log(lines)


# ============================================================
# 主流程：输入明文手机号 + 券名 → 完成写库 + 库存扣减 + 日志留痕
# ============================================================
def issue_coupon_to_shop(phone, coupon_name):
    conn = get_remote_connection()
    inserted = {'coupon_issue': None,
                'payment_record': [],
                'order_main': None}
    template_id = None
    committed = False
    try:
        cursor = conn.cursor()
        now_str = time.strftime('%Y-%m-%d')
        today_start = now_str + ' 00:00:00'

        # ---- ① SM4加密手机号 → client 表取用户（只读）----
        cursor.execute(
            "SELECT id, name FROM vehicle_erp.client WHERE phone = %s",
            (encrypt_phone(phone),))
        row = cursor.fetchone()
        if not row:
            msg = f"商城无此用户: {phone}"
            print(f"[发券失败] {msg}")
            _log_failure(phone, coupon_name, msg)
            return False
        client_id, client_name = row[0], row[1]

        # ---- ② 券名 → coupon_template 取模板、有效期、并检查余量 ----
        cursor.execute(
            "SELECT id, validity_days, total_quantity, issued_quantity "
            "FROM vehicle_erp.coupon_template "
            "WHERE template_name = %s", (coupon_name,))
        tpl = cursor.fetchone()
        if not tpl:
            msg = f"无此券模板: {coupon_name}"
            print(f"[发券失败] {msg}")
            _log_failure(phone, coupon_name, msg)
            return False
        template_id, validity_days = tpl[0], int(tpl[1])
        total_qty, issued_qty = int(tpl[2]), int(tpl[3])
        if DEDUCT_TOTAL and total_qty - issued_qty <= 0:
            msg = f"券已发完: {coupon_name} 共{total_qty} 已发{issued_qty}"
            print(f"[发券失败] {msg}")
            _log_failure(phone, coupon_name, msg)
            return False
        end_time = (dt.datetime.strptime(now_str, '%Y-%m-%d')
                    + dt.timedelta(days=validity_days)).strftime('%Y-%m-%d') \
                   + ' 23:59:59'

        # ---- ③ 唯一券码 → 写 coupon_issue ----
        coupon_no = make_unique_code(
            cursor,
            "SELECT id FROM vehicle_erp.coupon_issue WHERE coupon_no=%s",
            gen_coupon_no)
        cursor.execute("""
            INSERT INTO vehicle_erp.coupon_issue
              (coupon_no, template_id, client_id, coupon_type, min_condition,
               start_time, end_time, coupon_status, use_time, issue_source,
               create_time, update_time, coupon_source)
            VALUES (%s,%s,%s,4,0.00,%s,%s,'used',NOW(),'自动发放',NOW(),NOW(),0)
        """, (coupon_no, template_id, client_id, today_start, end_time))
        coupon_id = cursor.lastrowid
        inserted['coupon_issue'] = coupon_id

        # ---- ④ 券名 → product 取赠品商品信息（只读）----
        cursor.execute(
            "SELECT p.id, p.product_code, p.main_category, pc.name "
            "FROM vehicle_erp.product p "
            "LEFT JOIN vehicle_erp.product_category pc ON pc.id = p.main_category "
            "WHERE p.product_name=%s AND p.is_gift=1",
            (coupon_name,))
        prod = cursor.fetchone()
        if not prod:
            raise RuntimeError(f"无同名赠品商品: {coupon_name}")
        product_id, product_code, category_id, category_name = prod
        if category_name is None:
            category_name = ''

        # ---- ⑤ 用户绑定顾问（只读）----
        cursor.execute(
            "SELECT advisor_id FROM vehicle_erp.client_advisor_relation "
            "WHERE client_id=%s", (client_id,))
        adv = cursor.fetchone()
        advisor_id = adv[0] if adv else None

        # ---- ⑥ 唯一支付号 → 写 payment_record ----
        payment_no = make_unique_code(
            cursor,
            "SELECT id FROM vehicle_erp.payment_record WHERE payment_no=%s",
            lambda: make_native_code(cursor))
        cursor.execute("""
            INSERT INTO vehicle_erp.payment_record
              (client_id, payment_no, pay_method, business_type, pay_amount,
               pay_status, remark, pay_time, callback_time, callback_data,
               create_time, update_time)
            VALUES (%s,%s,'balance','service_order',0.00,4,
                    '钱包支付',NOW(),NULL,NULL,NOW(),NOW())
        """, (client_id, payment_no))
        inserted['payment_record'].append(cursor.lastrowid)

        # ---- ⑦ 唯一订单号 → 写 order_main ----
        order_no = make_unique_code(
            cursor,
            "SELECT id FROM vehicle_erp.order_main WHERE order_no=%s",
            lambda: make_native_code(cursor))
        cursor.execute("""
            INSERT INTO vehicle_erp.order_main
              (order_no, client_id, phone, client_name, order_type,
               is_recharge, product_id, product_name, product_code,
               category_id, category_name, amount, quantity,
               discount_amount, pay_amount, coupon_id, coupon_type,
               coupon_name, pay_method, payment_no, pay_status,
               payment_time, refund_reason, refund_time, order_status,
               store_id, store_name, store_address, verifier_name,
               appointment_time, verify_time, complete_time, remark,
               is_evaluate, advisor_id, create_time, update_time, is_gift)
            VALUES (%s,%s,%s,%s,'product',
                    0,%s,%s,%s,
                    %s,%s,0.00,1,
                    0.00,0.00,%s,4,
                    %s,'balance',%s,4,
                    NOW(),NULL,NULL,2,
                    NULL,NULL,NULL,NULL,
                    NULL,NULL,NULL,'钱包支付',
                    0,%s,NOW(),NOW(),1)
        """, (order_no, client_id, phone, client_name,
              product_id, coupon_name, product_code,
              category_id, category_name,
              coupon_id, coupon_name,
              payment_no,
              advisor_id))
        inserted['order_main'] = cursor.lastrowid

        # ---- ⑧ 扣减模板计数：issued_quantity +1 ----
        upd_total = ", total_quantity = total_quantity - 1" if DEDUCT_TOTAL else ""
        cursor.execute(
            f"UPDATE vehicle_erp.coupon_template "
            f"SET issued_quantity = issued_quantity + 1{upd_total} "
            f"WHERE id = %s", (template_id,))
        if cursor.rowcount != 1:
            raise RuntimeError("模板计数更新失败")

        conn.commit()
        committed = True

        # ---- 全部成功 → 写日志（含回滚SQL）----
        _log_success(inserted, phone, coupon_name, coupon_no,
                     payment_no, order_no, template_id)
        print(f"[发券成功] phone={phone} 券={coupon_name} "
              f"coupon_issue.id={inserted['coupon_issue']} "
              f"payment_record.id={inserted['payment_record'][0]} "
              f"order_main.id={inserted['order_main']} "
              f"order_no={order_no}")
        print(f"[日志已写入] {_get_log_file()}")
        return True

    except Exception as e:
        if not committed:
            conn.rollback()
        msg = f"{type(e).__name__}: {e}（数据库已回滚或未提交）"
        print(f"[发券异常] phone={phone} coupon={coupon_name}: {msg}")
        import traceback; traceback.print_exc()
        _log_failure(phone, coupon_name, msg)
        return False
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        conn.close()


