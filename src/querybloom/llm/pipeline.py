"""Multi-agent QA generation pipeline orchestration for single and batch subgraphs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import threading
from typing import Any, Dict, List, Optional, Tuple, Union
import yaml
from tqdm import tqdm

from querybloom.events import EventSink, emit_event
from querybloom.llm.complexity import introduce_complexity
from querybloom.llm.execution import execute_sparql_and_get_result
from querybloom.llm.generation import generate_and_execute
from querybloom.llm.prompts import (
    load_complexity_template,
    load_prompt_template,
    load_reword_template,
    load_verify_template,
    subsample_subgraph_entities,
)
from querybloom.llm.reword import reword_questions
from querybloom.llm.verification import verify_qa_pairs


def process_single_subgraph_pipeline(
    subgraph: Dict[str, Any],
    subgraph_index: int,
    endpoint: str,
    model: str,
    template: Any,
    timeout: int,
    fail_empty: bool = True,
    verify_iterations: int = 0,
    verify_template: Any = None,
    focus_entity_qa: bool = False,
    ents_ratio: float = 0.4,
    additional_instructions: str = "",
    introduce_complexity_step: bool = True,
    complexity_template: Any = None,
    reword_questions_step: bool = True,
    reword_template: Any = None,
    event_sink: EventSink | None = None,
    stop_event: Optional[threading.Event] = None,
) -> Dict[str, Any]:
    """
    Execute full multi-agent pipeline for a single subgraph:
    Generation -> SPARQL Execution -> Complexity -> Verification Cycles -> Rewording.
    """
    if stop_event is not None and stop_event.is_set():
        return {
            **subgraph,
            "is_meaningful": False,
            "cancelled": True,
            "qa_pairs": [],
            "source_subgraph_index": subgraph_index,
        }
    emit_event(
        event_sink,
        "subgraph.started",
        "llm.subgraph",
        f"Processing subgraph {subgraph_index}",
        {"subgraph_index": subgraph_index},
    )
    subgraph_for_prompt = subsample_subgraph_entities(subgraph, ents_ratio=ents_ratio)
    pattern_str = yaml.dump(
        subgraph_for_prompt, default_flow_style=False, sort_keys=False
    )
    emit_event(
        event_sink,
        "prompt.ready",
        "llm.prompt",
        f"Prompt pattern ready for subgraph {subgraph_index}",
        {"subgraph_index": subgraph_index, "pattern": pattern_str},
    )

    # --- Initial generate + execute ---
    gen_result, qa_pairs = generate_and_execute(
        subgraph=subgraph,
        subgraph_index=subgraph_index,
        endpoint=endpoint,
        model=model,
        template=template,
        timeout=timeout,
        fail_empty=fail_empty,
        pattern_str=pattern_str,
        focus_entity_qa=focus_entity_qa,
        additional_instructions=additional_instructions,
        event_sink=event_sink,
    )

    output_sg = dict(subgraph)
    output_sg["is_meaningful"] = gen_result.is_meaningful

    # --- Complexity introduction step ---
    if introduce_complexity_step and gen_result.is_meaningful and qa_pairs:
        emit_event(
            event_sink,
            "stage.started",
            "llm.complexity",
            f"Introducing complexity for subgraph {subgraph_index}",
            {"subgraph_index": subgraph_index, "num_pairs": len(qa_pairs)},
        )
        ci_result = introduce_complexity(
            subgraph_pattern=pattern_str,
            qa_pairs=qa_pairs,
            model=model,
            complexity_template=complexity_template,
            additional_instructions=additional_instructions,
        )
        for i, aug in enumerate(ci_result.augmentations):
            if aug.skipped or i >= len(qa_pairs):
                continue
            exec_result = execute_sparql_and_get_result(
                aug.augmented_sparql_query,
                endpoint=endpoint,
                timeout=timeout,
                fail_empty=fail_empty,
            )
            qa_pairs[i]["question"] = aug.augmented_text_query
            qa_pairs[i]["sparql_query"] = aug.augmented_sparql_query
            qa_pairs[i]["execution_results"] = exec_result
            qa_pairs[i]["complexity_types"] = aug.complexity_types
        emit_event(
            event_sink,
            "stage.completed",
            "llm.complexity",
            f"Complexity step completed for subgraph {subgraph_index}",
            {
                "subgraph_index": subgraph_index,
                "augmentations": [a.model_dump() for a in ci_result.augmentations],
            },
        )

    # No verification requested — original behaviour
    if verify_iterations == 0 or not gen_result.is_meaningful:
        if reword_questions_step and gen_result.is_meaningful and qa_pairs:
            emit_event(
                event_sink,
                "stage.started",
                "llm.reword",
                f"Rewording questions for subgraph {subgraph_index}",
                {"subgraph_index": subgraph_index, "num_pairs": len(qa_pairs)},
            )
            rw_result = reword_questions(qa_pairs, model, reword_template)
            for idx, rw in enumerate(rw_result.pairs):
                if (
                    idx < len(qa_pairs)
                    and rw.status == "needs_reword"
                    and rw.reworded_text_query
                ):
                    qa_pairs[idx]["pre_reword_question"] = qa_pairs[idx]["question"]
                    qa_pairs[idx]["question"] = rw.reworded_text_query
                    qa_pairs[idx]["reword_reason"] = rw.reason
            emit_event(
                event_sink,
                "stage.completed",
                "llm.reword",
                f"Rewording completed for subgraph {subgraph_index}",
                {
                    "subgraph_index": subgraph_index,
                    "pairs": [p.model_dump() for p in rw_result.pairs],
                },
            )
        output_sg["qa_pairs"] = qa_pairs
        emit_event(
            event_sink,
            "subgraph.completed",
            "llm.subgraph",
            f"Completed subgraph {subgraph_index}",
            {"subgraph_index": subgraph_index, "result": output_sg},
        )
        return output_sg

    # --- Verification loop ---
    for qa in qa_pairs:
        qa["pre_verify_question"] = qa["question"]
        qa["pre_verify_sparql_query"] = qa["sparql_query"]
    for iteration in range(1, verify_iterations + 1):
        emit_event(
            event_sink,
            "stage.started",
            "llm.verify",
            f"Verification cycle {iteration} for subgraph {subgraph_index}",
            {"subgraph_index": subgraph_index, "iteration": iteration},
        )
        v_result = verify_qa_pairs(
            subgraph_pattern=pattern_str,
            qa_pairs=qa_pairs,
            model=model,
            verify_template=verify_template,
            additional_instructions=additional_instructions,
        )
        emit_event(
            event_sink,
            "stage.completed",
            "llm.verify",
            f"Verification cycle {iteration} completed for subgraph {subgraph_index}",
            {
                "subgraph_index": subgraph_index,
                "iteration": iteration,
                "verification": v_result.model_dump(),
            },
        )

        for i, qa in enumerate(qa_pairs):
            pair_v = v_result.pairs[i] if i < len(v_result.pairs) else None
            status = pair_v.status if pair_v else "correct"
            qa["verification_status"] = status
            qa["verification_reason"] = pair_v.reason if pair_v else ""
            qa.setdefault("verification_status_by_cycle", []).append(status)

        if v_result.all_correct or iteration == verify_iterations:
            break

        # Apply fixes and re-execute only the fixed pairs
        for i, qa in enumerate(qa_pairs):
            pair_v = v_result.pairs[i] if i < len(v_result.pairs) else None
            if pair_v and pair_v.status == "needs_fix":
                qa["question"] = pair_v.fixed_text_query or qa["question"]
                qa["sparql_query"] = pair_v.fixed_sparql_query or qa["sparql_query"]
                qa["execution_results"] = execute_sparql_and_get_result(
                    qa["sparql_query"],
                    endpoint=endpoint,
                    timeout=timeout,
                    fail_empty=fail_empty,
                )

    output_sg["qa_pairs"] = qa_pairs
    output_sg["finalized_at_iteration"] = iteration
    output_sg["verification_status"] = (
        "correct" if v_result.all_correct else "needs_fix"
    )
    output_sg["most_meaningful_index"] = v_result.most_meaningful_index
    chosen = v_result.most_meaningful_index - 1
    if 0 <= chosen < len(qa_pairs):
        qa_pairs[chosen]["is_most_meaningful"] = True

    # --- Question reword step ---
    if reword_questions_step and qa_pairs:
        correct_indices = [
            i
            for i, qa in enumerate(qa_pairs)
            if qa.get("verification_status", "correct") == "correct"
        ]
        correct_pairs = [qa_pairs[i] for i in correct_indices]
        if correct_pairs:
            emit_event(
                event_sink,
                "stage.started",
                "llm.reword",
                f"Rewording correct questions for subgraph {subgraph_index}",
                {"subgraph_index": subgraph_index, "num_pairs": len(correct_pairs)},
            )
            rw_result = reword_questions(correct_pairs, model, reword_template)
            for ci, rw in zip(correct_indices, rw_result.pairs):
                if rw.status == "needs_reword" and rw.reworded_text_query:
                    qa_pairs[ci]["pre_reword_question"] = qa_pairs[ci]["question"]
                    qa_pairs[ci]["question"] = rw.reworded_text_query
                    qa_pairs[ci]["reword_reason"] = rw.reason
            emit_event(
                event_sink,
                "stage.completed",
                "llm.reword",
                f"Rewording completed for subgraph {subgraph_index}",
                {
                    "subgraph_index": subgraph_index,
                    "pairs": [p.model_dump() for p in rw_result.pairs],
                },
            )

    emit_event(
        event_sink,
        "subgraph.completed",
        "llm.subgraph",
        f"Completed subgraph {subgraph_index}",
        {"subgraph_index": subgraph_index, "result": output_sg},
    )
    return output_sg


def process_subgraphs_data(
    subgraphs: List[Dict[str, Any]],
    endpoint: str,
    model: str = "gpt-5",
    template_path: str = None,
    output_dir: str = None,
    timeout: int = 70,
    max_workers: int = 10,
    fail_empty: bool = False,
    verify_iterations: int = 0,
    max_subgraphs: int = None,
    subgraph_indices: List[int] | None = None,
    focus_entity_qa: bool = False,
    ents_ratio: float = 0.4,
    additional_instructions: str = "",
    introduce_complexity_step: bool = True,
    reword_questions_step: bool = True,
    input_label: str = "in-memory",
    input_filename: str = "subgraphs.yaml",
    event_sink: EventSink | None = None,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Process subgraphs in memory, generate questions, execute queries,
    and optionally save the results to YAML.
    """
    indexed_subgraphs = list(enumerate(subgraphs))
    if subgraph_indices is not None:
        requested = {int(index) for index in subgraph_indices}
        indexed_subgraphs = [
            (index, subgraph)
            for index, subgraph in indexed_subgraphs
            if index in requested
        ]

    if (
        subgraph_indices is None
        and max_subgraphs is not None
        and max_subgraphs < len(indexed_subgraphs)
    ):
        import random

        indexed_subgraphs = random.sample(indexed_subgraphs, max_subgraphs)

    subgraphs = [subgraph for _, subgraph in indexed_subgraphs]

    output_path = None
    if output_dir is not None:
        os.makedirs(output_dir, exist_ok=True)

        base, ext = os.path.splitext(os.path.basename(input_filename))
        if not ext:
            ext = ".yaml"
        model_slug = (
            model.split("/")[-1].replace(".", "").replace("-", "").replace("_", "").lower()
        )
        base_with_model = f"{base}-{model_slug}"
        output_path = os.path.join(output_dir, f"{base_with_model}{ext}")
        if os.path.exists(output_path):
            counter = 1
            while os.path.exists(
                os.path.join(output_dir, f"{base_with_model}-{counter}{ext}")
            ):
                counter += 1
            output_path = os.path.join(output_dir, f"{base_with_model}-{counter}{ext}")

    template = load_prompt_template(template_path)
    v_template = load_verify_template() if verify_iterations > 0 else None
    c_template = load_complexity_template() if introduce_complexity_step else None
    rw_template = load_reword_template() if reword_questions_step else None

    label = "Gen + Exec"
    if introduce_complexity_step:
        label += " + Complexity"
    if verify_iterations > 0:
        label += f" + Verify(×{verify_iterations})"
    if reword_questions_step:
        label += " + Reword"
    print(
        f"Processing {len(indexed_subgraphs)} subgraphs [{label}] with {max_workers} workers..."
    )
    emit_event(
        event_sink,
        "run.started",
        "llm.batch",
        "LLM subgraph processing started",
        {
            "input_source": input_label,
            "endpoint": endpoint,
            "model": model,
            "num_subgraphs": len(indexed_subgraphs),
            "subgraph_indices": [index for index, _ in indexed_subgraphs],
            "max_workers": max_workers,
            "label": label,
        },
    )

    output_subgraphs: List[Optional[Dict[str, Any]]] = [None] * len(indexed_subgraphs)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {
            executor.submit(
                process_single_subgraph_pipeline,
                sg,
                source_index,
                endpoint,
                model,
                template,
                timeout,
                fail_empty,
                verify_iterations,
                v_template,
                focus_entity_qa,
                ents_ratio,
                additional_instructions,
                introduce_complexity_step,
                c_template,
                reword_questions_step,
                rw_template,
                event_sink,
                stop_event,
            ): (output_index, source_index)
            for output_index, (source_index, sg) in enumerate(indexed_subgraphs)
        }

        for future in tqdm(
            as_completed(future_to_index),
            total=len(subgraphs),
            desc="Pipeline Progress (Gen + Exec)",
        ):
            if stop_event is not None and stop_event.is_set():
                for f in future_to_index:
                    f.cancel()
                emit_event(
                    event_sink,
                    "run.cancelled",
                    "llm.batch",
                    "QA generation cancelled by user",
                    {"stage": "llm.batch"},
                )
                break
            output_index, source_index = future_to_index[future]
            try:
                result = future.result()
                result["source_subgraph_index"] = source_index
                output_subgraphs[output_index] = result
                emit_event(
                    event_sink,
                    "subgraph.completed",
                    "llm.batch",
                    f"Stored result for subgraph {source_index}",
                    {"subgraph_index": source_index, "result": result},
                )
            except Exception as e:
                print(f"Error processing subgraph {source_index}: {e}")
                source_subgraph = indexed_subgraphs[output_index][1]
                output_subgraphs[output_index] = {
                    **source_subgraph,
                    "is_meaningful": False,
                    "error": str(e),
                    "qa_pairs": [],
                    "source_subgraph_index": source_index,
                }
                emit_event(
                    event_sink,
                    "error",
                    "llm.batch",
                    f"Error processing subgraph {source_index}",
                    {"subgraph_index": source_index, "error": str(e)},
                )

    final_subgraphs = [s for s in output_subgraphs if s is not None]

    if output_path is not None:
        with open(output_path, "w") as f:
            yaml.dump(
                final_subgraphs,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )

    if verify_iterations > 0:
        print("\n── Verification Summary ──")
        for it in range(1, verify_iterations + 1):
            correct = 0
            total = 0
            for sg in final_subgraphs:
                if sg.get("finalized_at_iteration") is None:
                    continue
                for qa in sg.get("qa_pairs", []):
                    history = qa.get("verification_status_by_cycle", [])
                    if it <= len(history):
                        status = history[it - 1]
                    else:
                        status = "correct"
                    total += 1
                    correct += int(status == "correct")
            rate = f"{correct}/{total} ({100*correct/total:.1f}%)" if total else "—"
            print(f"  After cycle {it}: {rate} pairs correct")
        print("──────────────────────────")

    emit_event(
        event_sink,
        "run.completed",
        "llm.batch",
        "LLM subgraph processing completed",
        {
            "output_path": output_path,
            "num_subgraphs": len(final_subgraphs),
            "subgraph_indices": [index for index, _ in indexed_subgraphs],
        },
    )
    return final_subgraphs, output_path


def process_subgraphs_yaml(
    input_yaml_path: str,
    endpoint: str,
    model: str = "gpt-5",
    template_path: str = None,
    output_dir: str = None,
    timeout: int = 70,
    max_workers: int = 10,
    fail_empty: bool = False,
    verify_iterations: int = 0,
    max_subgraphs: int = None,
    subgraph_indices: List[int] | None = None,
    focus_entity_qa: bool = False,
    ents_ratio: float = 0.4,
    additional_instructions: str = "",
    introduce_complexity_step: bool = True,
    reword_questions_step: bool = True,
    event_sink: EventSink | None = None,
) -> str:
    """Backward-compatible file-based wrapper around process_subgraphs_data."""
    with open(input_yaml_path, "r") as f:
        subgraphs = yaml.safe_load(f)

    if output_dir is None:
        input_dir = os.path.dirname(input_yaml_path)
        output_dir = os.path.join(input_dir, "qa_output")

    _, output_path = process_subgraphs_data(
        subgraphs=subgraphs,
        endpoint=endpoint,
        model=model,
        template_path=template_path,
        output_dir=output_dir,
        timeout=timeout,
        max_workers=max_workers,
        fail_empty=fail_empty,
        verify_iterations=verify_iterations,
        max_subgraphs=max_subgraphs,
        subgraph_indices=subgraph_indices,
        focus_entity_qa=focus_entity_qa,
        ents_ratio=ents_ratio,
        additional_instructions=additional_instructions,
        introduce_complexity_step=introduce_complexity_step,
        reword_questions_step=reword_questions_step,
        input_label=input_yaml_path,
        input_filename=os.path.basename(input_yaml_path),
        event_sink=event_sink,
    )
    assert output_path is not None
    return output_path
