"""Actions: buttons, confirmation boxes and modal forms."""

from .action import Action, ActionGroup, BulkAction, BulkActionGroup, Halt, flatten_actions
from .prebuilt import (
    AttachAction,
    CreateAction,
    DeleteAction,
    DeleteBulkAction,
    DetachAction,
    DetachBulkAction,
    EditAction,
    ForceDeleteAction,
    ForceDeleteBulkAction,
    ReplicateAction,
    RestoreAction,
    RestoreBulkAction,
    ViewAction,
)

__all__ = [
    "Action", "ActionGroup", "AttachAction", "BulkAction", "BulkActionGroup", "CreateAction", "DeleteAction",
    "DeleteBulkAction", "DetachAction", "DetachBulkAction", "EditAction", "ForceDeleteAction",
    "ForceDeleteBulkAction", "Halt", "ReplicateAction", "RestoreAction", "RestoreBulkAction", "ViewAction",
    "flatten_actions",
]
