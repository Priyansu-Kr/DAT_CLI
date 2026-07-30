# Feature Specification: DAT Control Center GUI Upgradation

## 1. Overview
The goal of this feature is to upgrade the Developer Automation Toolkit (DAT) from a pure CLI interface to a modern, reactive GUI dashboard. This dashboard allows developers to configure, preview, and export feature documentation in real-time.

## 2. UI Layout Architecture
The interface follows a **Side-by-Side (Master-Detail)** pattern:
- **Left Panel (350px):** The "Control Center" for input and configuration.
- **Right Panel (Flexible):** The "Live Preview" and Actions area.

---

## 3. Component Breakdown

### A. Left Panel: Control Center
The configuration zone for the document metadata and structure.

1.  **Ticket ID Field:** 
    *   **Feature:** Text input field.
    *   **Behavior:** Auto-prefilled using Git service (parsing branch name). Remains editable.
    *   **UI:** Modern border, label icon, placeholder text.

2.  **Feature Topic Field:**
    *   **Feature:** Multi-line text input field.
    *   **Behavior:** Auto-prefilled using Git service (parsing topic from branch). Remains editable.

3.  **Document Structure (Toggle Group):**
    *   **Feature:** A vertical list of high-quality **Switch** components.
    *   **Toggles:**
        *   **Header:** Toggle top heading.
        *   **Metadata Table:** Toggle the "Task Detail" grid.
        *   **AI Summary:** Toggle the generative overview.
        *   **Changes Done:** Toggle the concise bullet points.
        *   **Test Cases Table:** Toggle the Index/Case/Status table.
        *   **Screenshots:** Toggle the image section.

4.  **Assets & Evidence Zone:**
    *   **Feature:** A dashed-border container.
    *   **Purpose:** Drag-and-drop area for adding local screenshots to the document.

### B. Right Panel: Live Preview
A high-fidelity representation of the final `.docx` file.

1.  **Preview Header:**
    *   **Document Title:** Displays the current Feature Topic.
    *   **Export Button:** Triggers the `DocumentService` to generate the file on disk.

2.  **Virtual Document (The Preview):**
    *   **Behavior:** **Reactive.** Any change in the Left Panel (typing a letter or flipping a switch) instantly updates this view.
    *   **Sections:**
        *   **Title:** Arial Bold, Size 24.
        *   **Task Detail Table:** 2-column grid with padding and Arial font.
        *   **Changes Done Section:** "Affected Module" label followed by brief bullet points.
        *   **Test Cases Table:** 3-column grid (Index, Case, Status) with specific column weightage.

---

## 4. Visual Design Specifications
To maintain a professional developer tool aesthetic:

- **Typography:** 
    *   Interface: Inter / System Default.
    *   Document Preview: **Strictly Arial** (to match the Word template).
- **Colors:** 
    *   Background: Deep Dark (`#111315`).
    *   Cards/Containers: Surface Grey (`#1e1e1e`).
    *   Accents: Tech Blue (`#007bff`).
    *   Text: High-contrast white/light-grey.
- **Spacing:**
    *   Generous internal padding (20px - 40px) to prevent a "compacted" look.
    *   Specific row heights for tables (30pt equivalent).

---

## 5. Functional Flow (Audit)
1.  **Initialization:** Command `dat gui` is run. The `Container` initializes `GitService` to fetch the current branch.
2.  **State Loading:** `DATGuiApp` consumes the `GitInfo` and populates the "Ticket ID" and "Topic" state variables.
3.  **User Interaction:** User toggles "Metadata Table" OFF.
4.  **Reactive Update:** The app's state manager triggers a re-render of the `PreviewArea`. The Metadata Table disappears from the right side.
5.  **Export:** User clicks "Export DOCX". The app sends the current state (overrides) to the `DocumentService`, which saves the file using the refined `DocxRenderer`.

---

## 6. Development Notes for Future AI
*   **Rendering:** Use **Software Rendering** modes if hardware acceleration is unavailable (Virtual Machines).
*   **State Management:** Maintain a decoupled state so the Preview logic can be unit-tested without the UI.
*   **Expansion:** The structure is modular; adding a new Word section requires only a new toggle and a corresponding `if` block in `build_preview_content`.
