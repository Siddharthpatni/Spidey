"""The knowledge graph: entity extraction, edges, path-finding, and the
auto-ingestion that makes it self-building."""

from spidey.platform.core import graph


def test_entity_extraction_types():
    ents = dict((n, t) for t, n in graph.extract_entities(
        "We used Python and FastAPI with Docker for the Autonomous Driving project."))
    assert ents.get("python") == "language"
    assert ents.get("fastapi") == "framework"
    assert ents.get("docker") == "tool"
    assert ents.get("autonomous driving") == "concept"


def test_ingest_builds_connected_graph(client):
    graph.ingest_text("ROS2 uses Python. Python uses OpenCV. OpenCV powers YOLO for "
                      "Autonomous Driving.", source="test", central=("paper", "AV Survey"))
    st = graph.stats()
    assert st["nodes"] >= 4 and st["edges"] >= 3
    # the central paper node connects to the tech it covers
    nb = graph.neighbors("AV Survey")
    assert nb["found"] and any(o["name"] == "ros2" for o in nb["out"])


def test_shortest_path_between_concepts(client):
    graph.relate("framework", "ros2", "uses", "language", "python")
    graph.relate("language", "python", "uses", "framework", "opencv")
    graph.relate("framework", "opencv", "powers", "framework", "yolo")
    path = graph.shortest_path("ros2", "yolo")
    assert path["found"] and path["hops"] >= 1
    names = [p["name"] for p in path["path"]]
    # endpoints correct and each step is a real edge (BFS may find any valid route
    # since the shared graph accumulates nodes across the suite)
    assert names[0] == "ros2" and names[-1] == "yolo"
    assert all(step["via"] for step in path["path"][1:])


def test_brain_api_and_stats(client):
    client.post("/api/brain/ingest", json={
        "text": "Kubernetes orchestrates Docker containers with Prometheus monitoring.",
        "title": "Infra Notes"})
    st = client.get("/api/brain/stats").json()
    assert st["nodes"] > 0 and st["edges"] > 0
    g = client.get("/api/brain/graph").json()
    assert g["nodes"] and g["edges"]
    node = client.get("/api/brain/node/kubernetes").json()
    assert node["found"]
    r = client.get("/api/brain/path", params={"from_": "kubernetes", "to": "docker"}).json()
    assert r["found"]


def test_graph_autofills_from_resume(client):
    """Adding a resume must connect the person to their skills in the graph."""
    client.post("/api/match/resumes", json={
        "name": "GraphTester", "text": "Engineer skilled in Python, PyTorch and Kubernetes."})
    nb = graph.neighbors("You")
    skills = {o["name"] for o in nb["out"]}
    assert {"python", "pytorch", "kubernetes"} & skills


def test_weight_grows_on_repeat(client):
    a1 = graph.upsert_node("concept", "repeated concept")
    graph.upsert_node("concept", "repeated concept", bump=2.0)
    row = graph.db.one("SELECT weight FROM kg_nodes WHERE id=?", (a1,))
    assert row["weight"] >= 3.0
