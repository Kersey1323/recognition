from pymilvus import MilvusClient
# 这里填你 settings.py 里正确的 Milvus IP 地址和端口，比如 "http://192.168.100.12:19530" 
client = MilvusClient(uri="http://192.168.100.12:19530")

# 删掉已经损坏的集合，让后端框架稍后可以自动重建
client.drop_collection("railway_parts_resnet_512L")
client.drop_collection("railway_parts_hp_512L")
print("清理完毕")
exit()