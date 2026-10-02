import numpy as np
import random
import matplotlib.pyplot as plt

class Agent:
    def __init__(self, position):
        # Continuous position (optimizer searches here)
        self.position = np.array(position, dtype=float)

        # Binary feature mask (fitness is evaluated here)
        self.binary_position = None

        # Fitness value
        self.fitness = float("inf")


class EANGO:
    def __init__(
        self,
        obj_func,
        n_features,
        pop_size=30,
        max_iter=50,
        lb=0.0,
        ub=1.0,
        seed=42,
    ):
        self.initial_mutation = 0.30
        self.final_mutation = 0.02
        self.diversity_threshold = 0.05
        self.restart_ratio = 0.2
        self.elite_ratio = 0.2
        self.obj_func = obj_func
        self.n_features = n_features
        self.pop_size = pop_size
        self.max_iter = max_iter
        self.lb = lb
        self.ub = ub

        random.seed(seed)
        np.random.seed(seed)

        self.population = []
        self.best_agent = None
        self.convergence = []

    def initialize_population(self):
        """Create the initial population randomly."""
        self.population = []

        for _ in range(self.pop_size):
            position = np.random.uniform(
                self.lb,
                self.ub,
                self.n_features
            )

            agent = Agent(position)
            self.population.append(agent)

    def evaluate_population(self):
        """
        Evaluate every agent using binary feature selection.
        """

        for agent in self.population:

            agent.binary_position = self.binary_conversion(agent.position)

            agent.fitness = self.obj_func(agent.binary_position)

    def update_best(self):
        """
        Update the global best agent.
        """

        current_best = min(self.population, key=lambda x: x.fitness)

        if self.best_agent is None or current_best.fitness < self.best_agent.fitness:

            self.best_agent = Agent(current_best.position.copy())

            self.best_agent.binary_position = current_best.binary_position.copy()

            self.best_agent.fitness = current_best.fitness

    def adaptive_factor(self, iteration):
        """
        Nonlinear adaptive exploration-exploitation factor.
        High exploration at the beginning,
        smooth transition to exploitation.
        """

        return 2 * np.exp(-3 * iteration / self.max_iter)

    def update_position(self, agent, iteration):
        """
        Adaptive movement towards the best solution.
        """

        A = self.adaptive_factor(iteration)

        r1 = np.random.rand(self.n_features)
        r2 = np.random.rand(self.n_features)

        candidate = (
            agent.position
            + A * r1 * (self.best_agent.position - agent.position)
            + 0.1 * r2 * np.random.randn(self.n_features)
        )

        candidate = np.clip(candidate, self.lb, self.ub)

        return candidate
    
    def binary_conversion(self, position):
        """
        Convert continuous position to binary feature mask.
        """
        probability = 1 / (1 + np.exp(-position))
        binary = (np.random.rand(self.n_features) < probability).astype(int)

        # Ensure at least one feature is selected
        if np.sum(binary) == 0:
            binary[np.random.randint(self.n_features)] = 1
        return binary

    def opposition_position(self, position):
        """
        Generate an opposite solution for the current position.
        """

        opposite = self.lb + self.ub - position

        opposite = np.clip(
            opposite,
            self.lb,
            self.ub
        )

        return opposite
    
    def get_elites(self):
        """
        Return the top-performing elite agents.
        """
        sorted_population = sorted(
            self.population,
            key=lambda agent: agent.fitness
        )

        elite_count = max(1, int(self.pop_size * self.elite_ratio))

        return sorted_population[:elite_count]
    
    def elite_guidance(self, position, elites, iteration):
        """
        Guide a solution toward a randomly selected elite using
        an adaptive elite influence.
        """

        elite = random.choice(elites)

        r = np.random.rand(self.n_features)

        # Adaptive elite influence
        elite_weight = 0.2 + 0.6 * (1 - iteration / self.max_iter)

        guided_position = (
            position
            + elite_weight * r * (elite.position - position)
        )

        guided_position = np.clip(
            guided_position,
            self.lb,
            self.ub
        )

        return guided_position

    def population_diversity(self):
        """
        Compute average population diversity.
        """
        positions = np.array([agent.position for agent in self.population])

        centroid = np.mean(positions, axis=0)

        diversity = np.mean(
            np.linalg.norm(positions - centroid, axis=1)
        )

        return diversity

    def restart_weak_agents(self):
        """
        Restart weakest agents to increase diversity.
        """

        sorted_population = sorted(
            self.population,
            key=lambda x: x.fitness,
            reverse=True
        )

        restart_count = max(
            1,
            int(self.pop_size * self.restart_ratio)
        )

        for agent in sorted_population[:restart_count]:

            # Generate a new continuous position
            agent.position = np.random.uniform(
            self.lb,
            self.ub,
            self.n_features
            )

            # Create corresponding binary feature mask
            agent.binary_position = self.binary_conversion(agent.position)

            # Evaluate the binary solution
            agent.fitness = self.obj_func(agent.binary_position)

    def mutation_rate(self, iteration):
        """
        Adaptive mutation rate.
        High at the beginning, low at the end.
        """
        return (
            self.initial_mutation
            - (self.initial_mutation - self.final_mutation)
            * (iteration / self.max_iter)
        )

    def adaptive_mutation(self, position, iteration):
        """
        Apply adaptive mutation.
        """

        rate = self.mutation_rate(iteration)

        mutated = position.copy()

        for i in range(self.n_features):

            if np.random.rand() < rate:

                mutated[i] = np.random.uniform(
                    self.lb,
                    self.ub
                )

        return np.clip(mutated, self.lb, self.ub)
    
    def optimize(self):
        """
        Main optimization loop.
        Returns the best binary solution and its fitness.
        """

        # -----------------------------
        # Step 1: Initialize population
        # -----------------------------
        self.initialize_population()

        # -----------------------------
        # Step 2: Evaluate population
        # -----------------------------
        self.evaluate_population()

        # -----------------------------
        # Step 3: Find initial best
        # -----------------------------
        self.update_best()

        # Save initial convergence point
        self.convergence.append(self.best_agent.fitness)

        # -----------------------------
        # Step 4: Optimization loop
        # -----------------------------
        for iteration in range(self.max_iter):

            # Elite agents
            elites = self.get_elites()

            for agent in self.population:

                # ----------------------------------
                # Generate new candidate
                # ----------------------------------
                candidate_position = self.update_position(
                    agent,
                    iteration
                )

                # Elite guidance
                candidate_position = self.elite_guidance(
                    candidate_position,
                    elites,
                    iteration
                )

                # Adaptive mutation
                candidate_position = self.adaptive_mutation(
                    candidate_position,
                    iteration
                )

                # Binary conversion
                binary_candidate = self.binary_conversion(
                    candidate_position
                )

                # Fitness
                candidate_fitness = self.obj_func(
                    binary_candidate
                )

                # ----------------------------------
                # Opposition-Based Learning
                # ----------------------------------
                opposite_position = self.opposition_position(
                    candidate_position
                )

                binary_opposite = self.binary_conversion(
                    opposite_position
                )

                opposite_fitness = self.obj_func(
                    binary_opposite
                )

                # Keep better solution
                if opposite_fitness < candidate_fitness:

                    candidate_position = opposite_position.copy()
                    binary_candidate = binary_opposite.copy()
                    candidate_fitness = opposite_fitness

                # ----------------------------------
                # Greedy selection
                # ----------------------------------
                if candidate_fitness < agent.fitness:

                    agent.position = candidate_position.copy()
                    agent.binary_position = binary_candidate.copy()
                    agent.fitness = candidate_fitness

            # ----------------------------------
            # Update global best
            # ----------------------------------
            self.update_best()

            # Save convergence
            self.convergence.append(
                self.best_agent.fitness
            )

            # ----------------------------------
            # Diversity preservation
            # ----------------------------------
            diversity = self.population_diversity()

            if diversity < self.diversity_threshold:
                self.restart_weak_agents()

            print(
                f"Iteration {iteration + 1}/{self.max_iter} | "
                f"Best Fitness: {self.best_agent.fitness:.6f}"
            )


        plt.figure(figsize=(8,5))

        plt.plot(
        range(1, len(self.convergence)+1),
        self.convergence,
        linewidth=2
        )

        plt.xlabel("Iteration")
        plt.ylabel("Best Fitness")
        plt.title("EA-NGO Convergence Curve")
        plt.grid(True)

        plt.savefig("EA_NGO_Convergence.png", dpi=300)

        plt.close()

        print("\nConvergence graph saved as EA_NGO_Convergence.png")
        # -----------------------------
        # Return best solution
        # -----------------------------
        return (
            self.best_agent.binary_position.copy(),
            self.best_agent.fitness
        )