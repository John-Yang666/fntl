import { openDB } from 'idb';

const DB_NAME = 'appDatabase';
const STORE_NAME = 'appStore';

// 初始化 IndexedDB
async function getDB() {
  return openDB(DB_NAME, 1, {
    upgrade(db) {
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME);
      }
    },
  });
}

// 存储数据
export async function saveToDB<T>(key: string, value: T): Promise<void> {
  const db = await getDB();
  await db.put(STORE_NAME, value, key);
}

// 读取数据
export async function getFromDB<T>(key: string): Promise<T | null> {
  const db = await getDB();
  return (await db.get(STORE_NAME, key)) || null;
}

// 删除数据
export async function deleteFromDB(key: string): Promise<void> {
  const db = await getDB();
  await db.delete(STORE_NAME, key);
}
