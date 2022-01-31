import numpy as np
from matplotlib import pyplot as plt
from scipy import stats
import summaries


def generate_data(m: int, n: int, entropy_method: str, scale: float) -> dict:  # pragma: no cover
    """
    Generate synthetic data that exemplifies the sensitivity of mutual information to prior choice.

    Args:
        m: Number of independent samples for estimating the entropy.
        n: Number of observations per sample.
        entropy_method: Nearest neighbor method for estimatingn the mutual information.
        scale: Scale of each prior distribution.
    """
    # Sample from the left and right priors.
    thetas = {
        'left': np.random.normal(-1, scale, m),
        'right': np.random.normal(1, scale, m),
    }

    results = {}
    for key, theta in thetas.items():
        # Sample from the likelihood.
        left = np.random.normal(0, np.exp(theta[:, None] / 2), (m, n))
        right = np.random.normal(theta[:, None], 1, (m, n))
        x = np.where(theta[:, None] < 0, left, right)

        # Evaluate the summary statistics.
        mean = x.mean(axis=-1)
        log_var = np.log(x.var(axis=-1))

        # Store the results in a dictionary for later plotting.
        results[key] = {
            'theta': theta,
            'x': x,
            'mean': mean,
            'log_var': log_var,
            'mi_mean': summaries.estimate_mutual_information(theta, mean, method=entropy_method),
            'mi_log_var': summaries.estimate_mutual_information(theta, log_var,
                                                                method=entropy_method),
        }

    return results


def _plot_example(m: int = 10000, n: int = 100, entropy_method: str = 'singh',
                  scale: float = .25, num_points: int = 200) -> None:  # pragma: no cover
    results = generate_data(m, n, entropy_method, scale)

    fig, axes = plt.subplots(2, 2, sharex=True)

    ax = axes[0, 0]
    for mu in [-1, 1]:
        lin = mu + np.linspace(-1, 1, 100) * 3 * scale
        prior = stats.norm(mu, scale)
        label = fr'$\theta\sim\mathrm{{Normal}}\left({mu}, 0.1\right)$'
        line, = ax.plot(lin, prior.pdf(lin), label=label)
        ax.axvline(mu, color=line.get_color(), ls=':')
    ax.set_ylabel(r'Density $P(\theta)$')

    ax = axes[1, 0]
    lin = np.linspace(-1, 1, 100) * (1 + 3 * scale)
    ax.plot(lin, np.maximum(0, lin), label=r'Location', color='k')
    ax.plot(lin, np.minimum(np.exp(lin / 2), 1), label=r'Scale', color='k', ls='--')
    ax.legend(fontsize='small', ncol=2)
    ax.set_ylabel('Likelihood parameters')

    step = m // num_points  # Only plot `num_points` for better visualisation.
    for key, result in results.items():
        for ax, s in zip(axes[:, 1], ['mean', 'log_var']):
            mi = result[f"mi_{s}"].mean()
            # Very close to zero, we may end up with negative results. Let's manually fix that.
            if abs(mi) < 1e-3:
                mi = abs(mi)
            ax.scatter(result['theta'][::step], result[s][::step], marker='.', alpha=.5,
                       label=fr'${key.title()}$ prior ($\hat{{I}}={mi:.2f}$)')

    axes[0, 1].set_ylabel(r'$\bar x$')
    axes[1, 1].set_ylabel(r'$\log\mathrm{var}\,x$')
    [ax.legend(fontsize='small', handletextpad=0, loc=loc)
     for ax, loc in zip(axes[:, 1], ['upper left', 'lower right'])]
    [ax.set_xlabel(r'Parameter $\theta$') for ax in axes[1]]
    fig.tight_layout()
