from fastapi import FastAPI

app = FastAPI()


@app.post("/runs")
def create_run(task_id: str):
    raise NotImplementedError


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    raise NotImplementedError
