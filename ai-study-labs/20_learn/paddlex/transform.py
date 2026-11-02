import c as ppnlp
from paddlenlp.transformers import AutoTokenizer, AutoModelForSeq2SeqLM

# 加载预训练模型和分词器
model_name = "transformer-base-en-de"  # 以英德翻译模型为例
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForSeq2SeqLM.from_pretrained(model_name)

# 待翻译的英文文本
input_text = "Hello, how are you?"

# 对输入文本进行分词
inputs = tokenizer(input_text, return_tensors="pd")

# 进行翻译
outputs = model.generate(**inputs)

# 将模型输出转换为文本
translation = tokenizer.decode(outputs[0].numpy(), skip_special_tokens=True)
print("Translation:", translation)    