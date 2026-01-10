from typing import cast

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Container, VerticalGroup, VerticalScroll
from textual.reactive import Reactive, reactive
from textual.widget import Widget
from textual.widgets import Collapsible, Link, LoadingIndicator, Static

from gojeera.config import CONFIGURATION
from gojeera.models import JiraIssue
from gojeera.utils.urls import build_external_url_for_issue
from gojeera.widgets.create_work_item.screen import AddWorkItemScreen
from gojeera.widgets.work_item_details.read_only_details import WorkItemReadOnlyDetailsScreen


class SubtasksContainer(Container):
    """Container for holding subtask elements."""

    def __init__(self):
        super().__init__(id='subtasks-container')


class ChildWorkItemCollapsible(Collapsible):
    """A collapsible to show the work items that are children of another work item."""

    BINDINGS = [
        Binding(
            key='v',
            action='view_work_item',
            description='View Work Item',
            show=True,
            key_display='v',
        ),
    ]

    def __init__(self, *args, **kwargs):
        self._work_item_key: str = kwargs.pop('work_item_key', None)
        super().__init__(*args, **kwargs)
        self.border_title = self._work_item_key

    @property
    def work_item_key(self) -> str:
        return self._work_item_key

    async def action_view_work_item(self) -> None:
        await self.app.push_screen(WorkItemReadOnlyDetailsScreen(self.work_item_key))


class IssueChildWorkItemsWidget(VerticalScroll):
    HELP = 'See Subtasks section in the help'
    issues: Reactive[list[JiraIssue] | None] = reactive(None, always_update=True)

    BINDINGS = [
        # override the binding to be able to inject the current work item as a prent of the subtask
        Binding(
            key='ctrl+n',
            action='create_work_item_subtask',
            description='New Work Item',
            show=True,
            key_display='^n',
        ),
    ]

    def __init__(self):
        super().__init__(id='issue_subtasks')
        self._issue_key: str | None = None

    @property
    def help_anchor(self) -> str:
        return '#subtasks'

    @property
    def issue_key(self) -> str | None:
        return self._issue_key

    @issue_key.setter
    def issue_key(self, value: str | None) -> None:
        self._issue_key = value

    @property
    def loading_container(self) -> Center:
        return self.query_one('.tab-loading-container', Center)

    @property
    def content_container(self) -> VerticalGroup:
        return self.query_one('.tab-content-container', VerticalGroup)

    @property
    def subtasks_container_widget(self) -> SubtasksContainer:
        return self.query_one(SubtasksContainer)

    def compose(self) -> ComposeResult:
        with Center(classes='tab-loading-container') as loading_container:
            loading_container.display = False
            yield LoadingIndicator()
        with VerticalGroup(classes='tab-content-container') as content:
            content.display = True  # Ensure content container starts visible
            with SubtasksContainer():
                pass

    def show_loading(self) -> None:
        """Show the loading indicator and hide content."""
        self.loading_container.display = True
        self.content_container.display = False

    def hide_loading(self) -> None:
        """Hide the loading indicator and show content."""
        self.loading_container.display = False
        self.content_container.display = True

    async def action_create_work_item_subtask(self) -> None:
        screen = cast('MainScreen', self.screen)  # type:ignore[name-defined] # noqa: F821
        await self.app.push_screen(
            AddWorkItemScreen(
                project_key=screen.project_selector.selection,
                reporter_account_id=CONFIGURATION.get().jira_account_id,
                parent_work_item_key=self.issue_key,
            ),
            callback=screen.create_work_item,
        )

    def watch_issues(self, items: list[JiraIssue] | None) -> None:
        """Updates the list of work items that are subtasks of the currently-selected item.

        Args:
            items: the list of items that are subtasks of the current work item.

        Returns:
            None
        """
        # Get the subtasks container where subtasks will be mounted
        subtasks_container = self.subtasks_container_widget

        # Always clear existing children first
        subtasks_container.remove_children()

        # If no items, make sure content is visible (not loading) and leave container empty
        if not items:
            self.loading_container.display = False
            self.content_container.display = True
            return

        rows: list[ChildWorkItemCollapsible] = []
        for issue in items:
            children: list[Widget] = [
                Static(Text(f'Status: {issue.status_name}')),
                Static(Text(f'Type: {issue.issue_type.name}')),
                Static(Text(f'Assignee: {issue.display_assignee()}')),
            ]
            if browsable_url := build_external_url_for_issue(issue.key):
                children.append(
                    Link(
                        browsable_url, url=browsable_url, tooltip='open link in the default browser'
                    )
                )
            item_collapsible = ChildWorkItemCollapsible(
                *children,
                title=Text(issue.cleaned_summary()),
                work_item_key=issue.key,
            )
            item_collapsible.border_subtitle = issue.status_name
            rows.append(item_collapsible)

        # Mount the subtasks inside the SubtasksContainer
        subtasks_container.mount_all(rows)
