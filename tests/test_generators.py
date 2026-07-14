"""Unit tests for code generators."""
from models.schemas import (
    ExplorationTask, ExploreStep, StepAction, StepStatus, ElementLocator,
)
from generators.feature_generator import generate_feature_file, _sanitize_name
from generators.script_generator import generate_test_script
from generators.page_object_generator import generate_page_object
from generators._locator_utils import generate_playwright_locator


def test_sanitize_name():
    assert _sanitize_name("Hello World") == "Hello World"
    assert _sanitize_name("test@#$login") == "testlogin"

def test_generate_feature_file_empty():
    task = ExplorationTask(target_url="https://example.com", requirements="Basic check")
    steps = []
    result = generate_feature_file(task, steps)
    assert "Feature:" in result
    assert "Scenario:" in result

def test_generate_feature_file_with_steps():
    task = ExplorationTask(target_url="https://x.com", requirements="Login")
    steps = [
        ExploreStep(index=0, action=StepAction.NAVIGATE, description="Go to login",
                    value="https://x.com/login", status=StepStatus.SUCCESS),
        ExploreStep(index=1, action=StepAction.CLICK, description="Click submit",
                    locator=ElementLocator(name="Login", role="button"),
                    status=StepStatus.SUCCESS),
    ]
    result = generate_feature_file(task, steps)
    assert "Feature:" in result
    assert "login" in result.lower()

def test_generate_script_empty():
    task = ExplorationTask(target_url="https://x.com", requirements="Test")
    result = generate_test_script(task, [])
    assert "import pytest" in result
    assert "def test_" in result

def test_playwright_locator_label():
    loc = ElementLocator(label="Username")
    code = generate_playwright_locator(loc)
    assert "get_by_label" in code
    assert "Username" in code

def test_playwright_locator_role():
    loc = ElementLocator(role="button", name="Submit")
    code = generate_playwright_locator(loc)
    assert "get_by_role" in code
    assert "Submit" in code

def test_generate_page_object():
    steps = [
        ExploreStep(index=0, action=StepAction.CLICK, description="Click login",
                    locator=ElementLocator(name="Login", role="button"),
                    status=StepStatus.SUCCESS),
        ExploreStep(index=1, action=StepAction.FILL, description="Fill email",
                    locator=ElementLocator(label="Email"),
                    status=StepStatus.SUCCESS),
    ]
    result = generate_page_object(steps, page_name="TestPage")
    assert "class TestPage:" in result
    assert "get_by_role" in result or "get_by_label" in result
