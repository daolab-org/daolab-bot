from pymongo import MongoClient
from settings import settings

def mongo_db_url():
    return f"mongodb://{settings.mongo_user}:{settings.mongo_pass}@{settings.mongo_host}:{settings.mongo_port}"

def connect_mongodb():
    client = MongoClient(mongo_db_url())
    mydb = client["daolab"]
    mycoll = mydb["users"]
    return mycoll


if __name__ == '__main__':
    coll = connect_mongodb()
    coll.insert_one({
        "name": "Groot",
        "age": 999999,
        "address": "Asgard"
    })
    result = coll.find_one({"name": "Groot"})
    print(result)