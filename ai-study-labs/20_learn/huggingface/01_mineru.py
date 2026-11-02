from transformers import AutoModel, AutoTokenizer

model_name = "OpenDataLab/MinerU2.0-2505-0.9B"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModel.from_pretrained(model_name)