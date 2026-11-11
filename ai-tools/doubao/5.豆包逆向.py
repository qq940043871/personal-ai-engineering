import http.client
import json

conn = http.client.HTTPConnection("127.0.0.1", 8000)
payload = json.dumps({
   "model": "doubao",
   "messages": [
      {
         "role": "user",
         "content": "我是谁？"
      }
   ],
   "stream": False
})
headers = {
   'Authorization': 'Bearer REPLACE_WITH_YOUR_TOKEN',
   'User-Agent': 'Apifox/1.0.0 (https://apifox.com)',
   'Content-Type': 'application/json',
   'Accept': '*/*',
   'Host': '127.0.0.1:8000',
   'Connection': 'keep-alive'
}
conn.request("POST", "/v1/chat/completions", payload, headers)
res = conn.getresponse()
data = res.read()
print(data.decode("utf-8"))