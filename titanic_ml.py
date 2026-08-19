import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression

from sklearn.ensemble import RandomForestClassifier

df = pd.read_csv('titanic.csv')
df = df.fillna(0)
mean_age = df['Age'].mean()
df['Age'] = df['Age'].fillna(mean_age)

X = df.drop(columns=['2urvived'])
y = df['2urvived']

X_train,X_test,y_train,y_test = train_test_split(X, y, test_size=0.2, random_state=42)

model = RandomForestClassifier(n_estimators=100,max_depth=None,random_state=42)



#model = LogisticRegression(max_iter=1000)


model.fit(X_train, y_train)

predicions = model.predict(X_test)
print(pd.Series(predicions).value_counts())

scroes = model.score(X_test, y_test) * 100
print("ਅਸਲ ਸਕੋਰ",scroes)
if scroes >= 85:
	print("Model ਪੱਕਾ ਹੈ 💯✅:", scroes)
else:
	print("ਸਿਰਫ ਸੰਭਾਵਨਾ ਹੈ ਪੱਕਾ ਨਹੀਂ ")

