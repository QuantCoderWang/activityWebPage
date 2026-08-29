import mysql.connector
from config import DB_CONFIG
from sm4_util import encrypt_phone

def check_phone_registered(plain_phone: str) -> bool:
    """
    检查明文手机号在远程 MySQL 数据库中是否已注册
    
    逻辑：
    1. 先把明文手机号加密成 GJF_xxx 格式
    2. 连接远程数据库，查询 client 表的 phone 字段
    3. 查完立即关闭连接
    """
    # 加密手机号
    encrypted_phone = encrypt_phone(plain_phone)
    
    conn = None
    cursor = None
    try:
        # 建立连接
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        # 查询
        query = "SELECT COUNT(*) FROM client WHERE phone = %s"
        cursor.execute(query, (encrypted_phone,))
        
        count = cursor.fetchone()[0]
        
        return count > 0
        
    except mysql.connector.Error as err:
        print(f"[数据库错误] {err}")
        return False
    finally:
        # 立即关闭连接，不管成功还是失败
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


