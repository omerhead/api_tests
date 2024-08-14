import asyncio
import asyncpg
import httpx
import json
import redis

# Initialize Redis client
redis_client = redis.StrictRedis(host='localhost', port=6379, db=0)

async def fetch_tests_from_db():
    conn = await asyncpg.connect(user='postgres', password='123456',
                                 database='postgres', host='127.0.0.1')
    rows = await conn.fetch('SELECT * FROM api_tests ORDER BY dependency_id')
    await conn.close()
    return rows

async def execute_test(test):
    async with httpx.AsyncClient() as client:
        response = await client.request(
            method=test['request_method'],
            url=test['url'],
            json=json.loads(test['payload'])
        )
        return {
            'id': test['id'],
            'response_code': response.status_code,
            'response_json': response.json()
        }

async def save_results_to_redis(test_id, results):
    redis_key = f"test_result:{test_id}"
    redis_client.set(redis_key, json.dumps(results))

async def run_tests():
    tests = await fetch_tests_from_db()
    test_results = []
    for test in tests:
        result = await execute_test(test)
        test_results.append(result)
        await save_results_to_redis(test['id'], result)
        if result['response_code'] != test['expected_response_code'] or result['response_json'] != json.loads(test['expected_response_json']):
            print(f"Test {test['id']} failed.")
            print(f"code: {result['response_code']}")
            print(f"response: {result['response_json']}")
        else:
            print(f"Test {test['id']} passed.")

if __name__ == "__main__":
    asyncio.run(run_tests())
