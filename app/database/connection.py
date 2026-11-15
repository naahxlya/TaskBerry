from pymongo import MongoClient
from flask import current_app


def get_database():
    mongo_uri = current_app.config["MONGO_URI"]
    database_name = current_app.config["MONGO_DB"]

    client = MongoClient(
        mongo_uri,
        serverSelectionTimeoutMS=5000
    )

    client.admin.command("ping")

    return client[database_name]