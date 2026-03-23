# Feature Profiles

Each project using Context Forge defines a feature profile here. The profile configures domain-specific tags, terminology, output categories, and extraction hints that agents use during processing.

## Creating a Feature Profile

Create `{feature-name}.yaml` in this directory:

```yaml
name: my-feature
description: "Short description of the project"

tags:
  TAG1: "Component name — what it does"
  TAG2: "Another component — what it does"

terminology:
  TAG1: "Full name of TAG1"
  API: "Application Programming Interface"

output_categories:
  meetings: "Call transcripts, meeting notes, standups"
  documents: "Specs, design docs, reports"
  research: "Analysis, investigations"

extraction_hints:
  - "Decisions about architecture or design"
  - "Action items with owner and deadline"
```

Then set `active_feature` in `config.yaml` to your feature name.

## Feature files are not committed

Feature profiles contain project-specific terminology and are excluded from version control. Each user creates their own based on this template.
