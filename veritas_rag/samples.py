from typing import List, Dict, Any
from veritas_rag.chunker import chunker
from veritas_rag.storage import storage_service
from veritas_rag.config import config
import hashlib


LEGACY_SAMPLE_IDS = {
    "doc_solar_2023",
    "doc_cleantech_2025",
    "doc_grid_storage",
    "doc_arch_spec",
    "doc_incident_postmortem",
}

SAMPLE_DATASETS: List[Dict[str, Any]] = [
    {
        "id": "doc_dsa_foundations",
        "title": "DSA Notes: Complexity and Searching",
        "author": "NEXORA Study Notes",
        "year": None,
        "category": "Data Structures & Algorithms",
        "content": """# Complexity and Searching

## Time and Space Complexity
Big O describes how an algorithm's work grows as input size n grows. O(1) constant time stays bounded as n grows. O(log n) grows slowly by reducing the remaining problem, O(n) scans the input, and O(n log n) is common for efficient comparison sorting. O(n squared) often comes from comparing every pair. Space complexity measures extra memory used as input grows.

## Linear Search
Linear search checks items one at a time and works on unsorted data. Its best case is O(1), its average and worst cases are O(n), and its extra space is O(1).

## Binary Search
Binary search requires sorted data and random access, such as an array. Each comparison discards half the remaining range, giving O(log n) time and O(1) extra space in an iterative implementation. If the data is unsorted, sort it first or use linear search.

## Sorting Algorithms
Merge sort runs in O(n log n) time in the best, average, and worst cases and uses O(n) extra space for arrays. Heap sort runs in O(n log n) worst-case time and O(1) auxiliary array space. Quicksort averages O(n log n), but its worst case is O(n squared); randomized pivots reduce the chance of consistently poor partitions."""
    },
    {
        "id": "doc_dsa_arrays_hashing",
        "title": "DSA Notes: Arrays, Strings, and Hash Maps",
        "author": "NEXORA Study Notes",
        "year": None,
        "category": "Data Structures & Algorithms",
        "content": """# Arrays, Strings, and Hash Maps

## Arrays
An array stores items in indexed positions. Reading or updating an item by index takes O(1) time. Inserting or removing near the beginning usually takes O(n) time because later items shift. A dynamic array grows its capacity occasionally; append is amortized O(1), although a resize itself copies O(n) items.

## Two Sum Pattern
For Two Sum, scan the array once while a hash map stores each value's index. For each value x, check whether target minus x is already stored, then store x. This takes O(n) expected time and O(n) extra space. It returns a pair of indices without sorting the original array.

## Prefix Sums
A prefix-sum array stores the cumulative total through each position. After O(n) preprocessing, the sum of a range from l through r is prefix[r + 1] minus prefix[l], so each range query takes O(1) time. Prefix sums are useful when many range-sum queries use an unchanged array.

## Sliding Window
For a contiguous subarray or substring, a sliding window expands and shrinks two boundaries while maintaining a running condition. When each item enters and leaves at most once, the scan is O(n). This pattern is often useful for a longest substring with a constraint or a fixed-size window sum."""
    },
    {
        "id": "doc_dsa_linear_structures",
        "title": "DSA Notes: Linked Lists, Stacks, and Queues",
        "author": "NEXORA Study Notes",
        "year": None,
        "category": "Data Structures & Algorithms",
        "content": """# Linked Lists, Stacks, and Queues

## Linked Lists
A singly linked list stores a value and a pointer to the next node. Searching for a value or reaching index i takes O(n) time. Inserting at the head takes O(1). Inserting after a node whose reference is already known also takes O(1), but finding that node still takes O(n).

## Stacks
A stack follows last in, first out (LIFO). Push, pop, and peek take O(1) time when implemented with a dynamic array or a linked-list head. Stacks are useful for undo history, expression parsing, depth-first search, and matching brackets.

## Queues
A queue follows first in, first out (FIFO). Enqueue and dequeue take O(1) time with a linked list or a circular buffer. Removing the first item from a plain array may take O(n) because the remaining items shift. Queues are useful for scheduling and breadth-first search.

## Choosing a Structure
Use an array for fast indexed access. Use a stack when the newest item should be handled first. Use a queue when the oldest waiting item should be handled first. Use a linked list when frequent insertions at known nodes matter more than indexed access."""
    },
    {
        "id": "doc_dsa_trees_graphs",
        "title": "DSA Notes: Trees, Graphs, BFS, and DFS",
        "author": "NEXORA Study Notes",
        "year": None,
        "category": "Data Structures & Algorithms",
        "content": """# Trees and Graphs

## Binary Search Trees
A binary search tree stores smaller keys to the left and larger keys to the right. Search, insert, and delete take O(h), where h is the tree height. A balanced tree has height O(log n); a badly skewed tree can have height O(n). Inorder traversal of a binary search tree visits keys in sorted order.

## Breadth-First Search
Breadth-first search (BFS) explores a graph level by level using a queue. With an adjacency list it takes O(V + E) time and O(V) extra space, where V is the number of vertices and E is the number of edges. BFS finds shortest paths by edge count in an unweighted graph.

## Depth-First Search
Depth-first search (DFS) follows one path as far as possible before backtracking. It uses recursion or an explicit stack and takes O(V + E) time with an adjacency list. DFS is useful for connected components, cycle detection, and topological sorting of a directed acyclic graph.

## Dijkstra's Algorithm
Dijkstra's algorithm finds shortest paths from one source when edge weights are non-negative. With an adjacency list and a binary heap it takes O((V + E) log V) time. It is not correct for graphs with negative-weight edges; Bellman-Ford handles negative edges when there is no reachable negative cycle."""
    },
    {
        "id": "doc_dsa_dynamic_programming",
        "title": "DSA Notes: Recursion and Dynamic Programming",
        "author": "NEXORA Study Notes",
        "year": None,
        "category": "Data Structures & Algorithms",
        "content": """# Recursion and Dynamic Programming

## Recursion
Recursive algorithms solve a problem by calling themselves on smaller inputs. Every recursive solution needs a base case and progress toward that case. The call stack uses memory proportional to recursion depth.

## Dynamic Programming
Dynamic programming applies when subproblems overlap and an optimal solution can be composed from smaller subproblems. Memoization stores answers during top-down recursion. Tabulation builds answers bottom up in a table. Both avoid repeating the same subproblem.

## Fibonacci Example
Naive recursive Fibonacci repeats work and takes O(2 to the n) time. Memoization or tabulation computes each value once, taking O(n) time. A table uses O(n) space; an iterative version that keeps only the previous two values uses O(1) extra space.

## Problem-Solving Steps
Define the state in plain language, write the transition between states, specify base cases, and choose an evaluation order. Check the time and space cost from the number of states and transitions per state. For example, a grid with r rows and c columns may have O(r times c) states."""
    },
    {
        "id": "doc_dsa_complexity_pitfalls",
        "title": "DSA Practice Notes: Complexity Claims to Check",
        "author": "NEXORA Practice Set",
        "year": None,
        "category": "Data Structures & Algorithms",
        "content": """# Complexity Claims to Check

## Hash Map Lookup
Practice claim: hash map lookup is always O(1), regardless of input or collisions.

This claim is too strong. Hash map lookup is O(1) on average under a well-distributed hash function and controlled load factor, but can be O(n) in the worst case when many keys collide. State whether a complexity is average or worst case when explaining an answer.

## Search Requirements
Practice claim: binary search is a faster drop-in replacement for linear search on any collection.

This claim omits a requirement. Binary search needs sorted data and efficient access to the middle item. Linear search works on unsorted sequences. Choose based on the data's ordering and representation."""
    },
]


def load_sample_datasets(force_reload: bool = False):
    """Remove the old energy/software showcase and seed a small DSA learning set."""
    removed = 0
    for doc_id in LEGACY_SAMPLE_IDS:
        record = storage_service._documents.get(doc_id)
        if record and (record.get("metadata") or {}).get("owner_id") == config.owner_id:
            storage_service.delete_document(doc_id)
            removed += 1

    loaded_count = 0
    for item in SAMPLE_DATASETS:
        existing = storage_service._documents.get(item["id"])
        if existing and (existing.get("metadata") or {}).get("owner_id") == config.owner_id and not force_reload:
            continue
        if existing and (existing.get("metadata") or {}).get("owner_id") == config.owner_id:
            storage_service.delete_document(item["id"])

        meta = {
            "title": item["title"],
            "author": item["author"],
            "year": item["year"],
            "category": item["category"],
            "source_type": "study_sample",
            "owner_id": config.owner_id,
            "content_type": "text/plain",
            "uploaded_at": 0,
            "file_size_bytes": len(item["content"].encode("utf-8")),
            "content_hash": hashlib.sha256(item["content"].encode("utf-8")).hexdigest()[:16],
        }
        storage_service.add_document(item["id"], item["title"], meta, item["content"])
        chunks = chunker.chunk_document(item["id"], item["title"], item["content"], meta)
        storage_service.add_chunks(chunks)
        loaded_count += 1

    if loaded_count or removed:
        print(f"[Samples] Replaced legacy demos with {loaded_count} DSA study notes.")
