import json

class UserManager:
    def __init__(self):
        self.users = []
        self.db_connection = "sqlite:///users.db"

    def add_user(self, name, age, email):
        if age < 0 or age > 150:
            print("Invalid age")
            return
        if "@" not in email:
            print("Invalid email")
            return
        user = {"name": name, "age": age, "email": email, "role": "user"}
        self.users.append(user)
        print(f"User {name} added")

    def delete_user(self, email):
        for i, u in enumerate(self.users):
            if u["email"] == email:
                self.users.pop(i)
                print(f"Deleted {email}")
                return
        print("User not found")

    def get_report(self):
        total = len(self.users)
        ages = [u["age"] for u in self.users]
        avg = sum(ages) / total if total else 0
        report = f"Total: {total}, Avg Age: {avg:.1f}\n"
        for u in self.users:
            report += f"  - {u['name']} ({u['age']}) [{u['role']}]\n"
        return report

    def save_to_file(self, filename):
        with open(filename, "w") as f:
            json.dump(self.users, f)
        print(f"Saved to {filename}")

    def load_from_file(self, filename):
        with open(filename, "r") as f:
            self.users = json.load(f)
        print(f"Loaded from {filename}")

    def send_welcome_email(self, email):
        print(f"Connecting to SMTP server...")
        print(f"Sending welcome email to {email}")
        print(f"Email sent!")

    def promote_to_admin(self, email):
        for u in self.users:
            if u["email"] == email:
                u["role"] = "admin"
                self.send_welcome_email(email)
                return
        print("User not found")

    def generate_json_report(self):
        return json.dumps(self.users, indent=2)

    def generate_csv_report(self):
        lines = ["name,age,email,role"]
        for u in self.users:
            lines.append(f"{u['name']},{u['age']},{u['email']},{u['role']}")
        return "\n".join(lines)

    def validate_and_add(self, name, age, email, role="user"):
        if not name or len(name) < 2:
            print("Invalid name")
            return False
        if age < 0 or age > 150:
            print("Invalid age")
            return False
        if "@" not in email or "." not in email:
            print("Invalid email")
            return False
        if role not in ["user", "admin", "moderator"]:
            print("Invalid role")
            return False
        user = {"name": name, "age": age, "email": email, "role": role}
        self.users.append(user)
        if role == "admin":
            self.send_welcome_email(email)
        return True


manager = UserManager()
manager.validate_and_add("Alice", 30, "alice@example.com", "admin")
manager.validate_and_add("Bob", 25, "bob@example.com")
manager.validate_and_add("x", -1, "notanemail", "hacker")
print(manager.get_report())
print(manager.generate_csv_report())