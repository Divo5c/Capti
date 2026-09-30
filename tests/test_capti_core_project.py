"""
Tests für capti_core.project: Projektmodell + Workflow-Zustandsmaschine.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capti_core.project import (
    CaptiProject,
    InvalidTransitionError,
    ProjectWorkflow,
    WorkflowState,
    is_valid_video_path,
)


def _existing_video(tmp: str, name="video.mp4") -> str:
    path = os.path.join(tmp, name)
    with open(path, "wb") as f:
        f.write(b"\x00\x00\x00\x18ftypmp42")
    return path


class TestValidation(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_project_reports_errors(self):  # 1
        errors = CaptiProject().validation_errors()
        self.assertEqual(errors, ["error.no_video"])  # kein redundanter Zweitfehler

    def test_valid_project_has_no_errors(self):  # 2
        project = CaptiProject(video_path=_existing_video(self.tmp.name),
                               language="de", model="small")
        self.assertEqual(project.validation_errors(), [])

    def test_invalid_extension_rejected(self):  # 3
        project = CaptiProject(video_path=_existing_video(
            self.tmp.name, "not_video.txt"))
        self.assertIn("error.invalid_format", project.validation_errors())

    def test_missing_file_reported_separately(self):  # 4
        project = CaptiProject(video_path=os.path.join(
            self.tmp.name, "fehlt.mp4"))
        self.assertIn("error.video_missing", project.validation_errors())
        self.assertNotIn("error.invalid_format", project.validation_errors())

    def test_unknown_model_rejected(self):  # 5
        project = CaptiProject(video_path=_existing_video(self.tmp.name),
                               model="large-v3")
        self.assertIn("error.invalid_model", project.validation_errors())

    def test_extension_check_is_case_insensitive(self):  # 6
        self.assertTrue(is_valid_video_path("C:\\x\\Video.MOV"))
        self.assertFalse(is_valid_video_path("C:\\x\\video.gif"))


class TestSerialization(unittest.TestCase):

    def test_roundtrip(self):  # 7
        project = CaptiProject(video_path="/x/v.mp4", language="en",
                               model="base",
                               caption_style={"pop_scale": 120})
        clone = CaptiProject.from_dict(project.to_dict())
        self.assertEqual(clone, project)

    def test_from_dict_garbage_gives_safe_defaults(self):  # 8
        project = CaptiProject.from_dict(None)
        self.assertEqual(project.video_path, "")
        self.assertIsNone(project.language)
        self.assertEqual(project.model, "small")
        self.assertEqual(project.caption_style, {})

        project = CaptiProject.from_dict({"model": 42, "language": 7})
        self.assertEqual(project.model, "small")
        self.assertIsNone(project.language)

    def test_style_must_be_dict(self):  # 9
        project = CaptiProject.from_dict({"caption_style": ["kaputt"]})
        self.assertEqual(project.caption_style, {})


class TestWorkflow(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _workflow_with_video(self) -> ProjectWorkflow:
        return ProjectWorkflow(CaptiProject(video_path="/x/v.mp4"),
                               initial_state=WorkflowState.NEW_PROJECT)

    def test_happy_path_full_workflow(self):  # 10
        wf = self._workflow_with_video()
        self.assertTrue(wf.can_transition(WorkflowState.CAPTION_STYLE))
        wf.transition(WorkflowState.CAPTION_STYLE)
        self.assertTrue(wf.transition(WorkflowState.PROCESSING))
        wf.transition(WorkflowState.RESULT)
        wf.transition(WorkflowState.HOME)
        self.assertEqual(wf.state, WorkflowState.HOME)

    def test_back_navigation_new_project_to_home(self):  # 11
        wf = self._workflow_with_video()
        wf.transition(WorkflowState.HOME)

    def test_error_path_processing_to_caption_style(self):  # 12
        wf = self._workflow_with_video()
        wf.transition(WorkflowState.CAPTION_STYLE)
        wf.transition(WorkflowState.PROCESSING)
        wf.transition(WorkflowState.CAPTION_STYLE)   # Fehler/Abbruch
        self.assertEqual(wf.state, WorkflowState.CAPTION_STYLE)

    def test_illegal_transition_raises(self):  # 13
        wf = ProjectWorkflow()  # HOME
        with self.assertRaises(InvalidTransitionError):
            wf.transition(WorkflowState.PROCESSING)  # Home -> Processing

    def test_result_cannot_go_to_processing_directly(self):  # 14
        wf = self._workflow_with_video()
        wf.transition(WorkflowState.CAPTION_STYLE)
        wf.transition(WorkflowState.PROCESSING)
        wf.transition(WorkflowState.RESULT)
        self.assertFalse(wf.can_transition(WorkflowState.PROCESSING))

    def test_can_start_processing_requires_valid_project(self):  # 15
        wf = ProjectWorkflow(initial_state=WorkflowState.CAPTION_STYLE)
        self.assertFalse(wf.can_start_processing())  # kein Video gesetzt

        wf.project.video_path = _existing_video(self.tmp.name)
        self.assertTrue(wf.can_start_processing())

    def test_can_start_processing_requires_style_state(self):  # 16
        wf = ProjectWorkflow(CaptiProject(video_path="/x/v.mp4"))
        self.assertFalse(wf.can_start_processing())  # Zustand: HOME


if __name__ == "__main__":
    unittest.main()
