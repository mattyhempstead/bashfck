#!/usr/bin/env bash

for ((number = 2; number < 100; number++)); do
    prime=1

    for ((divisor = 2; divisor * divisor <= number; divisor++)); do
        if ((number % divisor == 0)); then
            prime=0
            break
        fi
    done

    if ((prime)); then
        printf '%s\n' "$number"
    fi
done
