# Paper Card: Code as Policies

**Title**: Code as Policies: Language Model Programs for Embodied Control
**Source**: https://arxiv.org/abs/2209.07753
**Date**: 2022
**Authors**: Jacky Liang, Wenlong Huang, Fei Xia, Peng Xu, Karol Hausman, Brian Ichter, Pete Florence, Andy Zeng (Google)
**Type**: Paper
**Core Problem**: How to use LLMs to generate robot control policies as executable code?
**Core Method**: LLM generates Python code that directly calls robot API functions. No fine-tuning needed.
**System Architecture**:
  - User provides natural language instruction
  - LLM generates Python code with robot API calls
  - Code is executed in sandboxed environment
  - Feedback loop for error correction
**Input**: Natural language instruction + robot API documentation
**Output**: Python code (robot policy)
**Action Space**: Python code calling robot manipulation APIs
**Memory Mechanism**: None (stateless code generation)
**Key Results**:
  - Effective robot manipulation from natural language
  - Generalizes to new instructions without training
  - Code composition enables complex multi-step policies
  - Works across different robot embodiments
**Borrowable Points**:
  - Code-as-action paradigm directly applicable to Minecraft
  - API documentation as context for LLM
  - Sandboxed execution model
  - Error handling and retry patterns
**Cannot Directly Adopt**:
  - Robot APIs differ from Minecraft APIs
  - No long-term memory or skill accumulation
**Suggestion**: Adopt the code-generation pattern for our skill library. LLM generates Mineflayer JavaScript code.
**Next Action**: Test LLM code generation quality for simple Mineflayer tasks
