from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import psycopg2
import os

app = FastAPI()

# Database connection
conn = psycopg2.connect(
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
)

class Item(BaseModel):
    id: int
    name: str

@app.get("/items", response_model=List[Item])
async def get_items():
    with conn.cursor() as cursor:
        cursor.execute("SELECT id, name FROM your_table")
        items = cursor.fetchall()
        return [{"id": id, "name": name} for id, name in items]

@app.post("/items", response_model=Item)
async def create_item(item: Item):
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO your_table (name) VALUES (%s) RETURNING id, name",
            (item.name,),
        )
        id, name = cursor.fetchone()
        conn.commit()
        return {"id": id, "name": name}

@app.put("/items/{item_id}", response_model=Item)
async def update_item(item_id: int, item: Item):
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE your_table SET name = %s WHERE id = %s RETURNING id, name",
            (item.name, item_id),
        )
        result = cursor.fetchone()
        if result is None:
            raise HTTPException(status_code=404, detail="Item not found")
        id, name = result
        conn.commit()
        return {"id": id, "name": name}

@app.delete("/items/{item_id}")
async def delete_item(item_id: int):
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM your_table WHERE id = %s", (item_id,))
        conn.commit()
        return {"message": "Item deleted successfully"}
