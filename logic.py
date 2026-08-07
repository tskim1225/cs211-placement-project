import json
import pandas as pd
import os
import mysql.connector
from sklearn.tree import DecisionTreeClassifier
from sklearn.multioutput import MultiOutputClassifier

# Keep exact passing logic
PASSING_CONFIG = {
    "Group_1_4": {
        "categories": [
            "Basic: loop/ for-each", "Basic: Method/parameter passing", 
            "Basic: If-else/Boolean zen", "Arrays/ArrayList"
        ],
        "abs_min": 4,         
        "pass_min": 6,         
        "min_pass_count": 3    
    },
    "Group_5_6": {
        "categories": ["Classes", "Inheritance/interfaces"],
        "abs_min": 5,          
        "pass_min": 7,         
        "min_pass_count": 1
    },
    "Group_7_8": {
        "categories": ["Java Collections Framework -HashSet", "Java Collections Framework -HashMap"],
        "abs_min": 4,          
        "pass_min": 5,         
        "min_pass_count": 1
    }
}

def load_questions():
    """Standard JSON loader"""
    base_path = os.path.dirname(__file__)
    file_path = os.path.join(base_path, 'questions.json')
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading questions: {e}")
        return []

def check_passing_status(category_scores):
    total_points = sum(score.get("correct", 0) * 2 for score in category_scores.values())

    # 1. Check Absolute Minimums (Hard Floor)
    for group_name, rules in PASSING_CONFIG.items():
        group_points = [category_scores.get(cat, {"correct": 0})["correct"] * 2 for cat in rules["categories"]]
        if not all(p >= rules["abs_min"] for p in group_points):
            return "Failed_Requirements" # Missed a specific category floor

    # 2. Check High-Score Requirements for "Pass"
    meets_all_high_score_rules = True
    for group_name, rules in PASSING_CONFIG.items():
        group_points = [category_scores.get(cat, {"correct": 0})["correct"] * 2 for cat in rules["categories"]]
        high_scores = sum(1 for p in group_points if p >= rules["pass_min"])
        if high_scores < rules["min_pass_count"]:
            meets_all_high_score_rules = False

    # 3. Final Logic
    if total_points >= 60 and meets_all_high_score_rules:
        return "Pass"
    elif total_points >= 48:
        return "Advice"
    else:
        # Met requirements, but score is 0-47
        return "Failed_Score"

def calculate_results(user_answers, questions):
    raw_correct = 0
    category_scores = {}
    
    # Map to store one tip per category from your JSON
    category_tips = {} 

    # Initialize scores
    for group in PASSING_CONFIG.values():
        for cat in group["categories"]:
            category_scores[cat] = {"correct": 0, "total": 0}

    for i, q in enumerate(questions):
        cat = q['category']
        
        # Capture the tip for this category if not already stored
        if cat not in category_tips and 'tip' in q:
            category_tips[cat] = q['tip']
            
        if cat in category_scores:
            category_scores[cat]["total"] += 1
            
        if i < len(user_answers) and user_answers[i] == q['answer']:
            raw_correct += 1
            category_scores[cat]["correct"] += 1

    # Prepare data for AI prediction (current points per category)
    row_data = {cat: score["correct"] * 2 for cat, score in category_scores.items()}
    
    # Get the categories the student needs to focus on (from AI or logic)
    needs_review_categories = get_multi_label_prediction(row_data)
    
    # Create the final recommendations list using tips from questions.json
    recommendations = []
    for cat in needs_review_categories:
        recommendations.append({
            "topic": cat,
            "summary": category_tips.get(cat, "Review core concepts in this area.") # Fallback text
        })
                
    display_points = int(raw_correct * 2)
    status = check_passing_status(category_scores)
    
    return display_points, recommendations, category_scores, status

def get_multi_label_prediction(row_data):
    """Predicts focus areas by pulling training data from the AWS RDS Database."""
    feature_cols = [
        "Basic: loop/ for-each", "Basic: Method/parameter passing", 
        "Basic: If-else/Boolean zen", "Arrays/ArrayList",
        "Classes", "Inheritance/interfaces", 
        "Java Collections Framework -HashSet", "Java Collections Framework -HashMap"
    ]
    target_cols = [f"T_{col}" for col in feature_cols]

    try:
        # 1. Connect to the Database
        db = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASS"),
            database=os.getenv("DB_NAME")
        )
        
        # 2. Pull the training data into a DataFrame
        # Note: We query the table we created in app.py
        query = "SELECT * FROM assessment_results"
        df = pd.read_sql(query, db)
        db.close()

        # 3. If we don't have enough data yet (e.g., < 10 students), use the 10-point rule
        if len(df) < 10:
            return [cat for cat in feature_cols if row_data.get(cat, 0) < 10]

        # 4. Prepare targets (AI needs 0 or 1 for training)
        for col in feature_cols:
            df[f"T_{col}"] = (df[col] < 10).astype(int)

        # 5. Train the AI Model
        X, y = df[feature_cols], df[target_cols]
        model = MultiOutputClassifier(DecisionTreeClassifier(max_depth=5))
        model.fit(X, y) # type: ignore
        
        # 6. Make the prediction for the current student
        current_input = pd.DataFrame([row_data])[feature_cols]
        prediction = model.predict(current_input)[0] # type: ignore
        
        return [feature_cols[i] for i, val in enumerate(prediction) if val == 1]

    except Exception as e:
        print(f"AI Training Error: {e}")
        # Fallback to simple logic if database is empty or fails
        return [cat for cat in feature_cols if row_data.get(cat, 0) < 8]