from datetime import datetime
import os
from dotenv import load_dotenv
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Random import get_random_bytes
import base64

load_dotenv()

class Account:
    def __init__(self, id=None, name=None, website=None, username=None, password=None, created_at=None, updated_at=None):
        self.id = id
        self.name = name
        self.website = website
        self.username = username
        self.password = password
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()
    
    def __repr__(self):
        return f"<Account(name='{self.name}', website='{self.website}')>"

class EncryptionUtil:
    def __init__(self):
        self.key = self._get_key()
    
    def _get_key(self):
        password = os.getenv('ENCRYPTION_KEY', 'default_encryption_key')
        salt = b'salt_123456'
        return PBKDF2(password, salt, dkLen=32)
    
    def encrypt(self, plaintext):
        cipher = AES.new(self.key, AES.MODE_EAX)
        nonce = cipher.nonce
        ciphertext, tag = cipher.encrypt_and_digest(plaintext.encode('utf-8'))
        return base64.b64encode(nonce + tag + ciphertext).decode('utf-8')
    
    def decrypt(self, ciphertext):
        data = base64.b64decode(ciphertext)
        nonce = data[:16]
        tag = data[16:32]
        ciphertext = data[32:]
        cipher = AES.new(self.key, AES.MODE_EAX, nonce=nonce)
        plaintext = cipher.decrypt_and_verify(ciphertext, tag)
        return plaintext.decode('utf-8')

encryption_util = EncryptionUtil()