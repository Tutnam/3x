import sqlite3, json
c = sqlite3.connect('users.db')
r = c.execute("select vless_profile_data from users where telegram_id=8994869678").fetchone()
d = json.loads(r[0]) if r and r[0] else {}
print(d)  # актуальный клиент
# d.pop("disabled", None)
# c.execute("update users set vless_profile_data=? where telegram_id=8994869678", (json.dumps(d),))
# c.commit()
# print("updated ->", d.get("email"))