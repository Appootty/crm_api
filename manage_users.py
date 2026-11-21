"""Manage portal users.  Run in this folder:
    python manage_users.py list
    python manage_users.py add <username> "<Full name>" [role]
    python manage_users.py passwd <username>
    python manage_users.py remove <username>
Passwords are asked for at the prompt and stored only as salted hashes."""
import getpass
import json
import sys

import auth_portal as a


def save(users):
    a.USERS_FILE.write_text(json.dumps({"users": users}, indent=2), encoding="utf-8")


def ask():
    p1 = getpass.getpass(f"Password (at least {a.MIN_PASSWORD} characters): ")
    if len(p1) < a.MIN_PASSWORD:
        sys.exit("Too short.")
    if p1 != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match.")
    return a.hash_password(p1)


def main():
    args = sys.argv[1:]
    users = a.load_users()
    if not args or args[0] == "list":
        for u in users:
            print(f"{u['username']:20s} {u.get('name', ''):28s} {u.get('role', '')}")
        return
    cmd = args[0]
    if cmd == "add" and len(args) >= 3:
        if a.find_user(args[1]):
            sys.exit("That username exists. Use passwd to change the password.")
        users.append({"username": args[1], "name": args[2], "role": args[3] if len(args) > 3 else "management", "password": ask()})
        save(users)
        print("Added.")
    elif cmd == "passwd" and len(args) == 2:
        u = next((x for x in users if x["username"].lower() == args[1].lower()), None)
        if not u:
            sys.exit("No such user.")
        u["password"] = ask()
        save(users)
        print("Password changed.")
    elif cmd == "remove" and len(args) == 2:
        save([u for u in users if u["username"].lower() != args[1].lower()])
        print("Removed (their session stops working immediately).")
    else:
        print(__doc__)


main()
