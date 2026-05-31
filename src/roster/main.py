from datetime import date
from fastapi import FastAPI
from roster.engine.generator import generate_basic_roster

app = FastAPI(
    title="Dental Roster API",
    description="Backend API for the dental clinic roster automation app.",
    version="0.1.0",
)

@app.get("/")
def root():
    return {
        "message": "Dental Roster API is running",
        "next_step": "Open /docs to view the API documentation",
    }

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/generate-roster")
def generate_roster(start_date: date, number_of_days: int = 7):
    roster = generate_basic_roster(start_date, number_of_days)
    return {
        "start_date": start_date,
        "number_of_days": number_of_days,
        "roster": roster,
    }