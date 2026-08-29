# 本程序为连接数据库的客户表加密手机号加密解密核心代码
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
from config import SM4_KEY, MY_PREFIX

def _pkcs5_pad(data: bytes) -> bytes:
    """PKCS5/PKCS7 填充"""
    padder = padding.PKCS7(128).padder()
    return padder.update(data) + padder.finalize()

def _pkcs5_unpad(data: bytes) -> bytes:
    """PKCS5/PKCS7 去填充"""
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(data) + unpadder.finalize()

def sm4_encrypt_hex(plaintext: str) -> str:
    """
    SM4 ECB PKCS5Padding 加密，返回十六进制字符串
    """
    key_bytes = SM4_KEY.encode('utf-8')
    plain_bytes = plaintext.encode('utf-8')
    
    # 填充
    padded_data = _pkcs5_pad(plain_bytes)
    
    # 加密
    cipher = Cipher(algorithms.SM4(key_bytes), modes.ECB(), backend=default_backend())
    encryptor = cipher.encryptor()
    encrypted_bytes = encryptor.update(padded_data) + encryptor.finalize()
    
    # 转为十六进制字符串
    return encrypted_bytes.hex()

def sm4_decrypt_hex(cipher_hex: str) -> str:
    """
    SM4 ECB PKCS5Padding 解密，输入为十六进制字符串
    """
    key_bytes = SM4_KEY.encode('utf-8')
    
    # 将十六进制字符串转换为字节数组
    cipher_bytes = bytes.fromhex(cipher_hex)
    
    # 解密
    cipher = Cipher(algorithms.SM4(key_bytes), modes.ECB(), backend=default_backend())
    decryptor = cipher.decryptor()
    decrypted_padded_bytes = decryptor.update(cipher_bytes) + decryptor.finalize()
    
    # 去填充
    plain_bytes = _pkcs5_unpad(decrypted_padded_bytes)
    
    return plain_bytes.decode('utf-8')

def encrypt_phone(plain_phone: str) -> str:
    """
    加密手机号，返回带前缀的完整密文
    """
    cipher_hex = sm4_encrypt_hex(plain_phone)
    return f"{MY_PREFIX}{cipher_hex}"

def decrypt_phone(encrypted_phone: str) -> str:
    """
    解密带前缀的手机号密文
    """
    if not encrypted_phone.startswith(MY_PREFIX):
        raise ValueError("密文缺少前缀")
    
    cipher_hex = encrypted_phone[len(MY_PREFIX):]
    return sm4_decrypt_hex(cipher_hex)
