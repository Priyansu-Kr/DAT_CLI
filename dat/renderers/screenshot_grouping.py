from typing import List, Optional, Tuple
from dat.models.screenshot_info import ScreenshotInfo

ScreenshotGroup = Tuple[Optional[int], str, List[ScreenshotInfo]]


def group_screenshots_by_test_case(
    screenshots: List[ScreenshotInfo],
    test_cases: List[str],
) -> List[ScreenshotGroup]:
    """Group screenshots under their assigned test case, preserving order.

    Returns a list of (case_index_or_None, label, screenshots) tuples, one
    per test case plus a trailing "Additional Screenshots" bucket for any
    unassigned shots (only present when at least one screenshot carries an
    explicit assignment).

    If no screenshot carries an explicit test_case_index, falls back to
    evenly distributing screenshots across test cases in order - this keeps
    the CLI flow (which never sets test_case_index) behaving exactly as
    before this grouping helper existed.
    """
    if not screenshots:
        return []

    num_cases = len(test_cases)
    if num_cases == 0:
        return [(None, "Screenshots", list(screenshots))]

    has_assignment = any(s.test_case_index is not None for s in screenshots)
    groups: List[ScreenshotGroup] = []

    if has_assignment:
        buckets = {i: [] for i in range(num_cases)}
        unassigned = []
        for s in screenshots:
            if s.test_case_index is not None and 0 <= s.test_case_index < num_cases:
                buckets[s.test_case_index].append(s)
            else:
                unassigned.append(s)
        for i, case_text in enumerate(test_cases):
            groups.append((i, f"Test Case {i + 1} : {case_text}", buckets[i]))
        if unassigned:
            groups.append((None, "Additional Screenshots", unassigned))
    else:
        num_shots = len(screenshots)
        avg = num_shots // num_cases
        remainder = num_shots % num_cases
        idx = 0
        for i, case_text in enumerate(test_cases):
            count = avg + (1 if i < remainder else 0)
            groups.append((i, f"Test Case {i + 1} : {case_text}", screenshots[idx: idx + count]))
            idx += count

    return groups
