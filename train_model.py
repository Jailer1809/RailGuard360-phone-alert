import os, joblib, pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix
from features import FEATURES
df = pd.read_csv("data/pushfall_dataset.csv")
if os.path.exists("data/real_samples.csv"):                 # windows recorded from your own camera (app.py --record LABEL)
    real = pd.read_csv("data/real_samples.csv"); df = pd.concat([df] + [real]*5); print("added real samples:", len(real))
Xtr, Xte, ytr, yte = train_test_split(df[FEATURES], df["label"], test_size=.25, stratify=df["label"], random_state=0)
clf = RandomForestClassifier(300, min_samples_leaf=3, random_state=0).fit(Xtr, ytr)
p = clf.predict(Xte); print(classification_report(yte, p, digits=3)); print(confusion_matrix(yte, p, labels=clf.classes_), clf.classes_)
os.makedirs("models", exist_ok=True); joblib.dump({"model": clf, "features": FEATURES}, "models/model.joblib"); print("saved models/model.joblib")
