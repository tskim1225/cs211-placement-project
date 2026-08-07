import os
import pandas as pd
import mysql.connector
from fastapi import FastAPI, Request, Response, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware # Added for security
from logic import load_questions, calculate_results, get_multi_label_prediction

app = FastAPI()

# SECURITY: This hides the password from the URL
app.add_middleware(SessionMiddleware, secret_key="cs211-secret-secure-key-99")

base_dir = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(base_dir, "templates"))

CSV_PATH = '/tmp/student_training_data.csv'

PROFESSOR_KEYS = {
    "Taesik Kim": "tk211!",
    "Tanuja Joshi": "tj211",
    "Varik Hoang": "vh1!",
    "Joseph Hueffed": "jh2@",
    "Garth Scheck": "gs211",
    "Xiao Li": "xl211"
}

FEATURE_COLS = [
    "Basic: loop/ for-each", "Basic: Method/parameter passing", 
    "Basic: If-else/Boolean zen", "Arrays/ArrayList",
    "Classes", "Inheritance/interfaces", 
    "Java Collections Framework -HashSet", "Java Collections Framework -HashMap"
]

def get_db_connection():
    # 1. Connect without selecting a database first
    conn = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS")
    )
    cursor = conn.cursor()
    # 2. Create the database if it doesn't exist using the DB_NAME environment variable
    db_name = os.getenv("DB_NAME", "student_placement_db")
    cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}`")
    cursor.execute(f"USE `{db_name}`")
    cursor.close()
    return conn

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/quiz", response_class=HTMLResponse)
async def start_quiz(
    request: Request,
    response: Response,
    sid: str = Form(...), 
    name: str = Form(...),
    professor: str = Form(...),
    session: str = Form(...),
    quarter: str = Form(...),
    year: str = Form(...)
):
    sid = sid.strip()
    if not sid.isdigit() or len(sid) != 9:
        return HTMLResponse("<h1>Invalid Student ID. Must be exactly 9 digits.</h1>", status_code=400)
    
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    
    questions = load_questions()
    return templates.TemplateResponse("quiz.html", {
        "request": request, "sid": sid, "name": name, "professor": professor,
        "session": session, "quarter": quarter, "year": year, "questions": questions
    })

@app.post("/submit", response_class=HTMLResponse)
async def handle_submit(
    request: Request, 
    sid: str = Form(...), 
    name: str = Form(...),
    professor: str = Form(...),
    session: str = Form(...),
    quarter: str = Form(...),
    year: str = Form(...)
):
    try:
        sid = sid.strip()
        form_data = await request.form()
        questions = load_questions()
        
        user_answers = []
        for q in questions:
            ans = form_data.get(f"q_{q['id']}")
            user_answers.append(ans if ans else "")
        
        points, recommendations, cat_scores, status = calculate_results(user_answers, questions)
        
        s_map = {
            "loops": cat_scores.get("Basic: loop/ for-each", {}).get('correct', 0),
            "methods": cat_scores.get("Basic: Method/parameter passing", {}).get('correct', 0),
            "logic": cat_scores.get("Basic: If-else/Boolean zen", {}).get('correct', 0),
            "arrays": cat_scores.get("Arrays/ArrayList", {}).get('correct', 0),
            "classes": cat_scores.get("Classes", {}).get('correct', 0),
            "inheritance": cat_scores.get("Inheritance/interfaces", {}).get('correct', 0),
            "hashset": cat_scores.get("Java Collections Framework -HashSet", {}).get('correct', 0),
            "hashmap": cat_scores.get("Java Collections Framework -HashMap", {}).get('correct', 0)
        }

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS assessment_results (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    sid VARCHAR(50), name VARCHAR(255), professor VARCHAR(255),
                    session VARCHAR(50), quarter VARCHAR(50), year VARCHAR(50),
                    score INT, status VARCHAR(50),
                    loops INT, methods INT, logic INT, arrays INT, 
                    classes INT, inheritance INT, hashset INT, hashmap INT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            sql = """INSERT INTO assessment_results 
                    (`sid`, `name`, `professor`, `session`, `quarter`, `year`, `score`, `status`, 
                    `loops`, `methods`, `logic`, `arrays`, `classes`, `inheritance`, `hashset`, `hashmap`) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
            
            cursor.execute(sql, (sid, name, professor, session, quarter, year, points, status,
                                 s_map['loops'], s_map['methods'], s_map['logic'], s_map['arrays'], 
                                 s_map['classes'], s_map['inheritance'], s_map['hashset'], s_map['hashmap']))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as db_e:
            print(f"Database Error: {db_e}")

        return templates.TemplateResponse("result.html", {
            "request": request,
            "points": points,
            "recommendations": recommendations, 
            "cat_scores": cat_scores,
            "status": status
        })
        
    except Exception as e:
        return HTMLResponse(content=f"<html><body><h1>Error: {e}</h1></body></html>", status_code=500)

# 1. This SHOWS the login page (GET)
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

# 2. This HANDLES the login button click (POST)
@app.post("/login")
async def login_submit(request: Request, professor: str = Form(...), key: str = Form(...)):
    if professor in PROFESSOR_KEYS and PROFESSOR_KEYS[professor] == key:
        request.session["user"] = professor 
        return RedirectResponse(url="/dashboard", status_code=303)
    
    return HTMLResponse(content="<h1>Access Denied</h1>", status_code=403)

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    prof_f = request.session.get("user")
    if not prof_f:
        return RedirectResponse(url="/login")

    sess_f = request.query_params.get("sess_f")
    qtr_f = request.query_params.get("qtr_f")
    yr_f = request.query_params.get("yr_f")

    try:
        conn = get_db_connection()
        df = pd.read_sql("SELECT * FROM assessment_results", conn)
        conn.close()
        
        df = df.rename(columns={
            'name': 'Student_Name', 
            'score': 'Total_Score', 
            'status': 'Status',
            'professor': 'Professor', 
            'session': 'Session', 
            'quarter': 'Quarter', 
            'year': 'Year',
            'sid': 'SID' 
        })
        
        for col in ['Professor', 'Session', 'Quarter', 'Year']:
            df[col] = df[col].astype(str).str.strip()

        df = df[df['Professor'] == str(prof_f).strip()]

        filters = {
            "sessions": sorted(df['Session'].unique().tolist()),
            "quarters": sorted(df['Quarter'].unique().tolist()),
            "years": sorted(df['Year'].unique().tolist())
        }

        if sess_f: df = df[df['Session'] == sess_f.strip()]
        if qtr_f: df = df[df['Quarter'] == qtr_f.strip()]
        if yr_f: df = df[df['Year'] == yr_f.strip()]

        averages = {
            "Basic: loop/ for-each": round(df['loops'].mean() * 2, 1) if not df.empty else 0,
            "Basic: Method/parameter passing": round(df['methods'].mean() * 2, 1) if not df.empty else 0,
            "Basic: If-else/Boolean zen": round(df['logic'].mean() * 2, 1) if not df.empty else 0,
            "Arrays/ArrayList": round(df['arrays'].mean() * 2, 1) if not df.empty else 0,
            "Classes": round(df['classes'].mean() * 2, 1) if not df.empty else 0,
            "Inheritance/interfaces": round(df['inheritance'].mean() * 2, 1) if not df.empty else 0,
            "Java Collections Framework -HashSet": round(df['hashset'].mean() * 2, 1) if not df.empty else 0,
            "Java Collections Framework -HashMap": round(df['hashmap'].mean() * 2, 1) if not df.empty else 0
        }

        all_students = df.sort_values(by='id', ascending=False).to_dict('records')
        
        return templates.TemplateResponse("admin.html", {
            "request": request, 
            "filters": filters, 
            "averages": averages, 
            "recent": all_students, 
            "selections": {"prof": prof_f, "sess": sess_f, "qtr": qtr_f, "yr": yr_f},
            "total_students": len(df)
        })
    except Exception as e:
        return HTMLResponse(f"Error loading dashboard: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)