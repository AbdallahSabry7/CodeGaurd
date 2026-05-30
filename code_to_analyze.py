import json
import os
from typing import List, Dict, Optional

class UserManager:
    def __init__(self):
        self.users = []
        self.admin_users = []

    def addUser(self, name, age, email, isAdmin=False):
        for u in self.users:
            if u['email'] == email:
                print("user already exists")
                return
        user = {'name': name, 'age': age, 'email': email}
        self.users.append(user)
        if isAdmin == True:
            self.admin_users.append(user)

    def getUser(self, email):
        for u in self.users:
            if u['email'] == email:
                return u
        return None

    def deleteUser(self, email):
        for i in range(len(self.users)):
            if self.users[i]['email'] == email:
                self.users.pop(i)
                for j in range(len(self.admin_users)):
                    if self.admin_users[j]['email'] == email:
                        self.admin_users.pop(j)
                        break
                return True
        return False

    def getAllUsers(self):
        return self.users

    def processUsers(self, data):
        result = []
        for i in range(len(data)):
            temp = data[i]
            if temp != None:
                if temp['age'] > 0:
                    if temp['age'] < 150:
                        result.append(temp)
        return result


def calculate_stats(userList):
    total = 0
    count = 0
    ages = []
    for i in range(len(userList)):
        total = total + userList[i]['age']
        count = count + 1
        ages.append(userList[i]['age'])
    avg = total / count
    mn = ages[0]
    mx = ages[0]
    for i in range(len(ages)):
        if ages[i] < mn:
            mn = ages[i]
        if ages[i] > mx:
            mx = ages[i]
    return avg, mn, mx


def saveToFile(users, FileName):
    f = open(FileName, 'w')
    json.dump(users, f)
    f.close()


def loadFromFile(FileName):
    if os.path.exists(FileName) == True:
        f = open(FileName, 'r')
        Data = json.load(f)
        f.close()
        return Data
    else:
        return []


def bad_helperFunc(x, y, z, flag1, flag2, flag3):
    TempResult = 0
    if flag1 == True:
        TempResult += x
    if flag2 == True:
        TempResult += y
    if flag3 == True:
        TempResult += z
    return TempResult