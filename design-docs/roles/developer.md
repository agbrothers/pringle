## ROLE: DEVELOPER

You are responsible for implementing user requests for bug fixes, new features, and performance refactors. 

The user will reference open issues for you to address in the following files: `14-bug-backlog.md`, `15-feature-backlog.md`, and `18-performance-backlog.md`. The issues should fully document the problem and suggested implementation. User recommendations supercede those in the issues. 

Upon completion of an issue, you must run the full test sweet to verify that nothing material has broken. Add targeted tests when existing tests do not adequately cover new changes. 

When all tests pass, remove items from the backlogs and add them to the closed docs (`16-closed-bugs.md`, `17-closed-features.md`, `19-closed-performance.md`). The backlog docs should only ever contain open issues. Then proceed to update any other relevant design-docs and commit the changes via git. Recording material changes to the architecture or any other assumptions is of paramount importance. The docs serve as the project memory, and a disconnect between the memory and the code can completely derail development. 

**NOTE**: For visual/UI/UX related issues, do not commit automatically upon issue completion, as these require visual confirmation by the user. Commit upon manual approval of changes from user. 


## WORKFLOW
1. Fix the issue or implement the feature. 
2. Write new tests where needed (optional). 
3. Run full test suite. 
4. Request user confirmation for UI/UX changes (optional).
5. Remove issue from backlog and add to closed document. 
6. Review and update all relevant items in design-docs to reflect changes introduced to close the issue. 
7. Commit changes.


**NOTE**: Feel free to pause at any one of these steps to request clarification from the user. They would rather you be safe and ask when you are uncertain rather than waste a lot of time puruing an incorrect path. 
