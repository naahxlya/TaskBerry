from pymongo import MongoClient
from flask import current_app


def get_database():
    database_name = current_app.config["MONGO_DB"]

    client = current_app.extensions.get("mongo_client")

    if client is None:
        mongo_uri = current_app.config["MONGO_URI"]

        client = MongoClient(
            mongo_uri,
            authMechanism="SCRAM-SHA-1",
            authSource="admin",
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=10000
        )

        client.admin.command("ping")

        current_app.extensions["mongo_client"] = client

    return client[database_name]