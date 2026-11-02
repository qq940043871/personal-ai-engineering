import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

class NLLBTranslator:
    def __init__(self, model_path, src_lang="zho_Hans", tgt_lang="eng_Latn"):
        """
        初始化 NLLB-200 翻译器
        
        参数:
        - model_path: 本地 NLLB-200 模型路径
        - src_lang: 源语言代码 (默认: 中文)
        - tgt_lang: 目标语言代码 (默认: 英文)
        """
        # 加载模型和分词器
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model_path)
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        
        # 设置语言代码
        self.src_lang = src_lang
        self.tgt_lang = tgt_lang
        
        # 移动模型到 GPU (如果可用)
        if torch.cuda.is_available():
            self.model = self.model.to("cuda")
    
    def translate(self, text, max_length=512, num_beams=4):
        """
        翻译文本
        
        参数:
        - text: 待翻译的文本
        - max_length: 生成文本的最大长度
        - num_beams: 束搜索宽度
        
        返回:
        - 翻译结果字符串
        """
        # 设置源语言前缀
        self.tokenizer.src_lang = self.src_lang
        
        # 编码输入文本
        inputs = self.tokenizer(text, return_tensors="pt")
        
        # 移动到 GPU (如果可用)
        if torch.cuda.is_available():
            inputs = {k: v.to("cuda") for k, v in inputs.items()}
        
        # 尝试获取目标语言的 ID
        try:
            forced_bos_token_id = self.tokenizer.convert_tokens_to_ids(self.tgt_lang)
        except KeyError:
            print(f"未找到 {self.tgt_lang} 对应的 ID，请检查语言代码。")
            return ""
        
        # 生成翻译
        translated_tokens = self.model.generate(
            **inputs,
            forced_bos_token_id=forced_bos_token_id,
            max_length=max_length,
            num_beams=num_beams,
            early_stopping=True
        )
        
        # 解码翻译结果
        translation = self.tokenizer.decode(
            translated_tokens[0], 
            skip_special_tokens=True
        )
        
        return translation


# 示例用法
if __name__ == "__main__":
    # 本地模型路径 (替换为你的实际路径)
    model_path = "facebook/nllb-200-distilled-600M"
    
    # 创建中英翻译器
    zh_en_translator = NLLBTranslator(
        model_path, 
        src_lang="zho_Hans",  # 中文（简体）
        tgt_lang="eng_Latn"   # 英文
    )
    
    # 创建英中翻译器
    en_zh_translator = NLLBTranslator(
        model_path, 
        src_lang="eng_Latn",  # 英文
        tgt_lang="zho_Hans"   # 中文（简体）
    )
    
    # 测试翻译
    chinese_text = "欢迎使用 OpenNMT 和 NLLB-200 进行翻译！"
    english_text = "Welcome to use OpenNMT and NLLB-200 for translation!"
    
    print(f"中文 → 英文: {zh_en_translator.translate(chinese_text)}")
    print(f"英文 → 中文: {en_zh_translator.translate(english_text)}")