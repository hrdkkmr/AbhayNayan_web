package in.abhaynayan.app.data

import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Index
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.RoomDatabase
import kotlinx.coroutines.flow.Flow

@Entity(tableName = "patients")
data class PatientEntity(
    @PrimaryKey val patientId: String,
    val displayName: String,
    val isSyntheticDemo: Boolean,
    val consentRecorded: Boolean,
    val createdAtUtc: String,
)

@Entity(tableName = "screenings", indices = [Index("patientId"), Index("createdAtUtc")])
data class ScreeningEntity(
    @PrimaryKey val screeningId: String,
    val patientId: String,
    val screeningType: String,
    val estimate: Double,
    val unit: String,
    val demoTag: String,
    val confidencePlaceholder: Double,
    val captureQualityProxy: Double,
    val modelMode: String = "DEMO",
    val synthetic: Boolean = true,
    val confirmationRequired: Boolean = true,
    val createdAtUtc: String,
)

@Dao
interface PatientDao {
    @Query("SELECT * FROM patients ORDER BY createdAtUtc DESC")
    fun observeAll(): Flow<List<PatientEntity>>

    @Query("SELECT COUNT(*) FROM patients")
    suspend fun count(): Int

    @Query("SELECT * FROM patients WHERE patientId = :id LIMIT 1")
    suspend fun find(id: String): PatientEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(patient: PatientEntity)
}

@Dao
interface ScreeningDao {
    @Query("SELECT * FROM screenings ORDER BY createdAtUtc DESC")
    fun observeAll(): Flow<List<ScreeningEntity>>

    @Query("SELECT COUNT(*) FROM screenings")
    suspend fun count(): Int

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insert(screening: ScreeningEntity): Long
}

@Database(entities = [PatientEntity::class, ScreeningEntity::class], version = 1, exportSchema = true)
abstract class AbhayDatabase : RoomDatabase() {
    abstract fun patientDao(): PatientDao
    abstract fun screeningDao(): ScreeningDao
}
