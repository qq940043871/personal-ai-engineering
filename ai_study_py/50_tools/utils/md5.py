import hashlib
import time

def generate_md5_hash(key,timespan, secret_key):
    
    # 拼接字符串
    message = key + timespan + secret_key
    
    # 计算MD5哈希值
    md5_hash = hashlib.md5(message.encode()).hexdigest()
    
    # 转换为大写
    md5_hash_upper = md5_hash.upper()
    
    return md5_hash_upper

# 示例使用
key = "3edf6769c88a441db4ef273cd035cf2f"
secret_key = "0FB982EA711C02F5C633D82909E0A7AB"
# 获取当前时间戳
timespan = str(int(time.time()))
encrypted_value = generate_md5_hash(key,timespan, secret_key)
print("加密后的值timespan:", timespan)
print("加密后的值TOKEN:", encrypted_value)