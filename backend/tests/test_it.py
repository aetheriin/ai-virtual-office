from app.agents.it_department import run_it_pipeline
from app.llm import extract_json


def test_extract_json_handles_fences():
    assert extract_json('ok ```json\n{"a": 1}\n``` done') == {"a": 1}
    assert extract_json("noise [1, 2] noise") == [1, 2]
    assert extract_json("no json") is None


async def test_it_pipeline_offline_order():
    events = []

    async def emit(ev, data):
        events.append((ev, data))

    state = await run_it_pipeline("Buatkan halaman login untuk timbangan sawit", emit)
    assert {"plan", "analysis", "code", "review"} <= state.keys()
    speakers = [d["agent"] for e, d in events if e == "agent:message"]
    assert speakers == ["pm", "analyst", "db", "be", "fe", "qa", "pm"]
