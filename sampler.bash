#!/bin/bash
#
# Parallel subgraph mining for multiple knowledge graphs
# Usage: bash sampler.bash
#

# Initialize conda
eval "$(conda shell.bash hook)"
conda activate m1

if [ $? -ne 0 ]; then
    echo "ERROR: Failed to activate conda environment 'm1'"
    exit 1
fi

echo "✓ Activated conda environment: m1"
echo "Python: $(which python)"
echo ""

# Knowledge graphs to process in parallel
KNOWLEDGE_GRAPHS=(
    "dream-kg"
    "secure-chain-kg"
    "rural-kg"
    "nasa-gesdisc-kg"
    "biobricks-aopwiki"
    "climatemodelskg"
)

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Create timestamped log directory (MM-DD-HH format)
TIMESTAMP=$(date +"%m-%d-%H")
LOG_DIR="${SCRIPT_DIR}/logs/${TIMESTAMP}"
mkdir -p "${LOG_DIR}"

echo "============================================================"
echo "SUBGRAPH MINING - PARALLEL MODE"
echo "============================================================"
echo "Knowledge Graphs to process: ${#KNOWLEDGE_GRAPHS[@]}"
for kg in "${KNOWLEDGE_GRAPHS[@]}"; do
    echo "  - ${kg}"
done
echo ""
echo "Logs will be saved to: ${LOG_DIR}"
echo "============================================================"
echo ""

# Store PIDs to wait for all processes
PIDS=()

# Start processing each KG in parallel with output redirected to log files
for kg in "${KNOWLEDGE_GRAPHS[@]}"; do
    LOG_FILE="${LOG_DIR}/${kg}.log"
    echo "Starting: ${kg} (log: ${LOG_FILE})"
    
    # Run sampler.py with output redirected to log file
    # Use unbuffered output (-u flag) for live logging
    python -u "${SCRIPT_DIR}/sampler.py" "${kg}" > "${LOG_FILE}" 2>&1 &
    
    # Store the PID
    PIDS+=($!)
done

echo ""
echo "All processes started! Waiting for completion..."
echo "You can monitor progress with:"
echo "  tail -f ${LOG_DIR}/*.log"
echo ""

# Wait for all background processes and collect exit codes
FAILED=0
SUCCEEDED=0

for i in "${!PIDS[@]}"; do
    pid=${PIDS[$i]}
    kg=${KNOWLEDGE_GRAPHS[$i]}
    
    # Wait for this process to complete
    wait $pid
    EXIT_CODE=$?
    
    if [ $EXIT_CODE -eq 0 ]; then
        echo "✓ ${kg} completed successfully"
        ((SUCCEEDED++))
    else
        echo "✗ ${kg} failed (exit code: ${EXIT_CODE})"
        ((FAILED++))
    fi
done

# Print summary
echo ""
echo "============================================================"
echo "PROCESSING COMPLETE - SUMMARY"
echo "============================================================"
echo "Total: ${#KNOWLEDGE_GRAPHS[@]} knowledge graphs"
echo "Succeeded: ${SUCCEEDED}"
echo "Failed: ${FAILED}"
echo "Logs saved to: ${LOG_DIR}"
echo "============================================================"
echo ""

# Exit with error if any process failed
if [ $FAILED -gt 0 ]; then
    exit 1
fi

exit 0
