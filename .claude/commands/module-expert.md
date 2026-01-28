# Module Expert

Load context for developing Hub modules - creating new modules or updating existing ones.

## Arguments

- `--design` - Also load the Hub system design document for architectural context

## Instructions

### Step 1: Load the module development guide

Read the authoritative guide for creating modules:
```
../hub-core/docs/guides/creating-modules.md
```

This covers:
- Module structure (manifest.json, tools/)
- Entities and routing
- Tool parameters
- Primitives and utilities
- Best practices

### Step 2: Load a reference implementation

Read the recipes module as a concrete example:
```
modules/recipes/manifest.json
```

Then read one tool to see the implementation pattern:
```
modules/recipes/tools/add_item
```

### Step 3: Load design document (if --design flag)

If the user passed `--design`, also read the Hub system design document:
```
../hub-core/docs/design/hub-design.md
```

This provides the bigger picture of how modules fit into the Hub architecture.

### Step 4: Summarize and prompt

After reading the files, provide a brief summary:

```
## Module Development Context Loaded

**Guide:** Creating modules (entities, tools, routing, primitives)
**Reference:** recipes module (manifest + add_item tool)
[If --design] **Architecture:** Hub system design

Ready to help with:
- Creating a new module from scratch
- Adding tools or entities to existing modules
- Configuring routing (aliases, actions, fast_match)
- Using primitives and utilities in tool scripts

What would you like to work on?
```

## Notes

- Do NOT summarize the content of the files in detail - just confirm they're loaded
- The context is now available for follow-up questions
- If the user wants to create a new module, help them start with a minimal manifest and first tool
- If updating an existing module, read that module's files first before making changes
