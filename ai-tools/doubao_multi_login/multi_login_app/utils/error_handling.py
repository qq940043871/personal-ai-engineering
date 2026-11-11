import logging
import traceback

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='app.log'
)
logger = logging.getLogger(__name__)

def handle_exception(func):
    """异常处理装饰器"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {str(e)}")
            logger.error(traceback.format_exc())
            return False
    return wrapper

def validate_account_data(name, website, username, password):
    """验证账户数据"""
    if not name or not isinstance(name, str) or len(name.strip()) == 0:
        return False, "账户名称不能为空"
    if not website or not isinstance(website, str) or len(website.strip()) == 0:
        return False, "网站地址不能为空"
    if not username or not isinstance(username, str) or len(username.strip()) == 0:
        return False, "用户名不能为空"
    if not password or not isinstance(password, str) or len(password.strip()) == 0:
        return False, "密码不能为空"
    return True, "验证通过"

def safe_execute(func, *args, **kwargs):
    """安全执行函数"""
    try:
        return True, func(*args, **kwargs)
    except Exception as e:
        logger.error(f"Safe execute error: {str(e)}")
        return False, str(e)