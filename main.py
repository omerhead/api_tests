import json
import asyncio
import asyncpg
from fastapi import FastAPI, HTTPException, Path, Query
from pydantic import BaseModel
from typing import Annotated, Coroutine, Optional, List, Dict, Any
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv
import httpx
from test_api import save_results_to_redis

# Load environment variables from .env file
load_dotenv()

# Database configuration from environment variables
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", 5432)

DB_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

app = FastAPI()

# CORS settings
origins = [
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models for request bodies
class APITest(BaseModel):
    url: str
    request_method: str
    payload: Optional[Dict[str, Any]]
    expected_response_code: int
    expected_response_json: Optional[Dict[str, Any]]
    dependency_id: Optional[int]

class APITestUpdate(APITest):
    id: int

class APITestDelete(BaseModel):
    id: int

class APITests(BaseModel):
    ids: List[int]

async def get_db_connection():
    try:
        conn = await asyncpg.connect(DB_URL)
        return conn
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection error: {str(e)}")

@app.post("/api_tests/", response_model=APITest)
async def create_api_test(api_test: APITest):
    conn = await get_db_connection()
    try:
        await conn.execute('''
            INSERT INTO api_tests (url, request_method, payload, expected_response_code, expected_response_json, dependency_id)
            VALUES ($1, $2, $3, $4, $5, $6)
        ''', api_test.url, api_test.request_method, json.dumps(api_test.payload), api_test.expected_response_code, json.dumps(api_test.expected_response_json), api_test.dependency_id)
    finally:
        await conn.close()
    return api_test

@app.put("/api_tests/{apiTestId}", response_model=APITestUpdate)
async def update_api_test(api_test_id: Annotated[int,Path(alias='apiTestId')], api_test: APITestUpdate):
    conn = await get_db_connection()
    try:
        result = await conn.execute('''
            UPDATE api_tests
            SET url = $1, request_method = $2, payload = $3, expected_response_code = $4, expected_response_json = $5, dependency_id = $6
            WHERE id = $7
        ''', api_test.url, api_test.request_method, json.dumps(api_test.payload), api_test.expected_response_code, json.dumps(api_test.expected_response_json), api_test.dependency_id, api_test_id)
        if result == "UPDATE 0":
            raise HTTPException(status_code=404, detail="API Test not found")
    finally:
        await conn.close()
    return api_test

@app.delete("/api_tests/{apiTestId}", response_model=APITestDelete)
async def delete_api_test(api_test_id: Annotated[int,Path(alias='apiTestId')]):
    conn = await get_db_connection()
    try:
        result = await conn.execute('''
            DELETE FROM api_tests WHERE id = $1
        ''', api_test_id)
        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="API Test not found")
    finally:
        await conn.close()
    return {"id": api_test_id}

@app.get("/api_tests/", response_model=Dict[str, Any])
async def get_api_tests(page: int = 1, itemsPerPage: int = 10, sortBy: Optional[str] = None):
    conn = await get_db_connection()
    try:
        offset = (page - 1) * itemsPerPage
        query = 'SELECT * FROM api_tests'
        if sortBy:
            sort_by = json.loads(sortBy)
            if sort_by:
                key = sort_by[0]['key']
                order = sort_by[0]['order']
                query += f' ORDER BY {key} {"DESC" if order == "desc" else "ASC"}'
        query += f' LIMIT {itemsPerPage} OFFSET {offset}'
        rows = await conn.fetch(query)
        api_tests = [dict(row) for row in rows]
        for api_test in api_tests:
            api_test['payload'] = json.loads(api_test['payload'])
            api_test['expected_response_json'] = json.loads(api_test['expected_response_json'])
        total = await conn.fetchval('SELECT COUNT(*) FROM api_tests')
    finally:
        await conn.close()
    return {"items": api_tests, "total": total}

@app.post("/run_test/", response_model=Dict[str, Any])
async def run_test(api_test_ids: APITests) -> Dict[str, Any]:
    conn = await get_db_connection()
    try:
        ids_tuple = tuple(api_test_ids.ids)
        if not ids_tuple:
            raise HTTPException(status_code=400, detail="Invalid request")
        
        query = "SELECT * FROM api_tests WHERE id = ANY($1)"
        
        rows = await conn.fetch(query, ids_tuple)
        api_tests = [dict(row) for row in rows]
        
        for api_test in api_tests:
            res = await execute_test(api_test)
            api_test['result'] = res
            await save_results_to_redis(api_test['id'], res)
            
            if res['response_code'] != api_test['expected_response_code'] or res['response_json'] != json.loads(api_test['expected_response_json']):
                print(f"Test {api_test['id']} failed.")
                print(f"code: {res['response_code']}")
                print(f"response: {res['response_json']}")
                api_test['state'] = "failed"
            else:
                print(f"Test {api_test['id']} passed.")
                api_test['state'] = "passed"
    finally:
        await conn.close()
    
    return {"items": api_tests}
            
async def execute_test(test) -> Dict[str, Any]:
    async with httpx.AsyncClient() as client:
        response = await client.request(
            method=test['request_method'],
            url=test['url'],
            json=json.loads(test['payload'])
        )
        try:
            response_json = response.json()
        except json.JSONDecodeError:
            response_json = None

        return {
            'id': test['id'],
            'response_code': response.status_code,
            'response_json': response_json
        }
