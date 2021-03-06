from sklearn.linear_model import ElasticNet, Lasso, BayesianRidge, LassoLarsIC
from sklearn.ensemble import RandomForestRegressor,  GradientBoostingRegressor
from sklearn.kernel_ridge import KernelRidge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import RobustScaler
from sklearn.base import BaseEstimator, TransformerMixin, RegressorMixin, clone
from sklearn.model_selection import KFold, cross_val_score, train_test_split
from sklearn.metrics import mean_squared_error
import xgboost as xgb
import lightgbm as lgb
import numpy as np

def rmse(y_true,y_pred):
    return np.sqrt(mean_squared_error(y_true,y_pred))



def eval_model(model,X,y,n_splits=10):

    score = np.zeros(n_splits)
    i = 0
    kf = KFold(n_splits=n_splits, random_state=50)
    for train_ind,test_ind in kf.split(X):

        xtrain,ytrain = X.iloc[train_ind],y.iloc[train_ind]
        # print('xtrain shape is ',xtrain.describe(),'ytrain shape is ',ytrain.describe())
        model.fit(xtrain,ytrain)
        y_cv = model.predict(X.iloc[test_ind])
        score[i] = rmse(y_cv,y.iloc[test_ind])
        i+=1
    mean_rmse = np.mean(score)
    print('mean RMSE is %.5f'%mean_rmse,'std RMSE is ', np.std(score))

    return mean_rmse

def eval_submodels(models, x, y):
    print('Cross_validation..')
    n_splits_val = 10
    kf = KFold(n_splits=n_splits_val, shuffle=False)
    for m_i, model in enumerate(models.regressors):
        rmse_buf = np.empty(n_splits_val)
        idx = 0
        for train, test in kf.split(x):
            model.fit(x.iloc[train], y.iloc[train])
            y_cv = model.predict(x.iloc[test])
            rmse_buf[idx] = rmse(y.iloc[test], y_cv)
            # print('Interation #' + str(idx) + ': RMSE = %.5f' % rmse_buf[idx])
            idx += 1

        mean_rmse = np.mean(rmse_buf)
        print('Model #' + str(m_i) + ': mean RMSE = %.5f' % mean_rmse + \
              ' +/- %.5f' % np.std(rmse_buf))



class AverageEnsemble(BaseEstimator, RegressorMixin):
    def __init__(self, regressors=None):
        self.regressors = regressors

    def fit(self, X, y):
        for regressor in self.regressors:
            regressor.fit(X, y)

    def predict(self, X):
        self.predictions_ = list()
        for regressor in self.regressors:
            self.predictions_.append(regressor.predict(X).ravel())

        # res = 0.45*self.predictions_[1] + 0.25*self.predictions_[0] + 0.30*self.predictions_[2]
        res = np.mean(self.predictions_, axis=0)

        return res




class StackingEnsemble(object):
    def __init__(self, n_splits, stacker, base_models):
        self.n_splits = n_splits
        self.stacker = stacker
        self.base_models = base_models

    def fit_predict(self, X, y, T):
        X = np.array(X)
        y = np.array(y)
        T = np.array(T)
        kf = KFold(n_splits=self.n_splits, shuffle=True, random_state=42)

        S_train = np.zeros((X.shape[0], len(self.base_models)))
        S_test = np.zeros((T.shape[0], len(self.base_models)))
        for i, clf in enumerate(self.base_models):
            S_test_i = np.zeros((T.shape[0], kf.get_n_splits()))
            for j, (train_idx, test_idx) in enumerate(kf.split(X)):
                X_train = X[train_idx]
                y_train = y[train_idx]
                X_holdout = X[test_idx]
                # y_holdout = y[test_idx]
                clf.fit(X_train, y_train)
                y_pred = clf.predict(X_holdout).ravel()
                S_train[test_idx, i] = y_pred
                S_test_i[:, j] = clf.predict(T).ravel()
            S_test[:, i] = S_test_i.mean(1)
        self.stacker.fit(S_train, y)
        y_pred = self.stacker.predict(S_test)[:]
        return y_pred


class StackingAveragedModels(BaseEstimator, RegressorMixin, TransformerMixin):
    def __init__(self, base_models, meta_model, n_folds=5):
        self.base_models = base_models
        self.meta_model = meta_model
        self.n_folds = n_folds

    # We again fit the data on clones of the original models
    def fit(self, X, y):
        self.base_models_ = [list() for x in self.base_models]
        self.meta_model_ = clone(self.meta_model)
        kfold = KFold(n_splits=self.n_folds, shuffle=True, random_state=156)

        # Train cloned base models then create out-of-fold predictions
        # that are needed to train the cloned meta-model
        out_of_fold_predictions = np.zeros((X.shape[0], len(self.base_models)))
        for i, model in enumerate(self.base_models):
            for train_index, holdout_index in kfold.split(X, y):

                self.base_models_[i].append(model)
                model.fit(X.iloc[train_index], y.iloc[train_index])
                y_pred = model.predict(X.iloc[holdout_index])
                out_of_fold_predictions[holdout_index, i] = y_pred

        # Now train the cloned  meta-model using the out-of-fold predictions as new feature
        self.meta_model_.fit(out_of_fold_predictions, y)
        return self

    # Do the predictions of all base models on the test data and use the averaged predictions as
    # meta-features for the final prediction which is done by the meta-model
    def predict(self, X):
        meta_features = np.column_stack([model.predict(X) for model in self.base_models]).mean(axis=1)
        return self.meta_model_.predict(meta_features)