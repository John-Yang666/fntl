import redis

# 连接到 Redis 服务器
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

def main():
    pubsub = redis_client.pubsub()
    pubsub.subscribe('test_channel')
    print("Subscribed to 'test_channel' on Redis.")

    try:
        for message in pubsub.listen():
            if message['type'] == 'message':
                data = message['data']
                print(f"Received message: {data}")
    except KeyboardInterrupt:
        print("Exiting subscriber.")

if __name__ == "__main__":
    main()
