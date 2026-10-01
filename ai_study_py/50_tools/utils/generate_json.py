import json

data = []
for i in range(1, 19):
    record = {
        "id": i,
        "name": f"姓名{i}",
        "age": 20 + (i % 30),
        "email": f"name{i}@example.com",
        "address": {
            "street": f"街道{i}号",
            "city": "示例城市",
            "postalCode": f"{100000 + i}"
        },
        "hobbies": ["爱好1", "爱好2", "爱好3"],
        "employment": {
            "company": f"公司{i}",
            "position": f"职位{i}",
            "yearsOfExperience": i % 25
        }
    }
    data.append(record)

with open('complex_data.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=4)